import datetime
import os

from config import get_indent_step
from models import Task, get_minutes
from os_utils import BackupManager, FileFinder, FileWriter
from parser.file_model import RawLine, TaskBlock, parse, serialize
from .state import DayCache, WeekState, _populate_task_relations
from .utils import root_task, week_expanded

DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']


def ensure_day_loaded(cache: dict, day: datetime.date, directory: str) -> DayCache:
    key = day.isoformat()
    if key not in cache:
        files = FileFinder.find_journal_files(directory, date_from=day, date_to=day)
        if files:
            nodes = parse(files[0])
            with open(files[0], 'r', encoding='utf-8') as f:
                original_content = f.read()
            _populate_task_relations(nodes)
            cache[key] = DayCache(
                file_path=files[0],
                nodes=nodes,
                original_content=original_content,
                task_list=[n.task for n in nodes if isinstance(n, TaskBlock)],
            )
        else:
            cache[key] = DayCache(
                file_path=None,
                nodes=[],
                original_content='',
                task_list=[],
            )
    return cache[key]


def reload_day_in_cache(cache: dict, day: datetime.date, directory: str) -> None:
    """Re-parse a day's file and replace its cache entry with a fresh baseline."""
    key = day.isoformat()
    files = FileFinder.find_journal_files(directory, date_from=day, date_to=day)
    if files:
        nodes = parse(files[0])
        with open(files[0], 'r', encoding='utf-8') as f:
            original_content = f.read()
        _populate_task_relations(nodes)
        cache[key] = DayCache(
            file_path=files[0],
            nodes=nodes,
            original_content=original_content,
            task_list=[n.task for n in nodes if isinstance(n, TaskBlock)],
        )
    else:
        cache[key] = DayCache(file_path=None, nodes=[], original_content='', task_list=[])


def cache_has_changes(cache: dict) -> bool:
    return any(serialize(day.nodes) != day.original_content for day in cache.values())


def save_cache(cache: dict, directory: str) -> None:
    for key, day in cache.items():
        content = serialize(day.nodes)
        if content == day.original_content:
            continue
        if day.file_path is None:
            day.file_path = os.path.join(directory, f"{key}.md")
        if os.path.exists(day.file_path):
            BackupManager.backup(day.file_path, directory)
        FileWriter.write_atomic(day.file_path, content.splitlines(keepends=True))
        day.original_content = content


def remove_block(nodes: list, block: TaskBlock) -> bool:
    """Remove a TaskBlock from nodes (searches recursively). Returns True if found."""
    for i, node in enumerate(nodes):
        if node is block:
            nodes.pop(i)
            return True
        if isinstance(node, TaskBlock):
            if remove_block(node.nodes, block):
                return True
    return False


def append_block(nodes: list, block: TaskBlock) -> None:
    """Append a TaskBlock with a blank-line separator when the list is non-empty."""
    if nodes:
        nodes.append(RawLine('\n'))
    nodes.append(block)


def sort_timed_nodes(nodes: list) -> None:
    """Sort top-level TaskBlocks by start time in-place; untimed tasks follow timed."""
    blocks = [n for n in nodes if isinstance(n, TaskBlock)]
    timed = sorted([b for b in blocks if b.task.time],
                   key=lambda b: get_minutes(b.task.time.start))
    untimed = [b for b in blocks if not b.task.time]
    sorted_blocks = timed + untimed
    if sorted_blocks == blocks:
        return
    # Only insert blank separators if the original list already had them between tasks.
    has_separator = any(
        isinstance(nodes[i], RawLine) and not nodes[i].raw.strip()
        and any(isinstance(nodes[j], TaskBlock) for j in range(i))
        and any(isinstance(nodes[j], TaskBlock) for j in range(i + 1, len(nodes)))
        for i in range(len(nodes))
    )
    first_block_idx = next((i for i, n in enumerate(nodes) if isinstance(n, TaskBlock)), len(nodes))
    leading = nodes[:first_block_idx]
    task_section = []
    for i, block in enumerate(sorted_blocks):
        if i > 0 and has_separator:
            task_section.append(RawLine('\n'))
        task_section.append(block)
    nodes.clear()
    nodes.extend(leading)
    nodes.extend(task_section)


def sync_body_to_block(block: TaskBlock, task: Task) -> None:
    """Rebuild block.nodes body lines from task.body, preserving existing child blocks."""
    indent_step = get_indent_step()
    child_blocks = {id(n.task): n for n in block.nodes if isinstance(n, TaskBlock)}
    new_nodes = []
    if task.body:
        body_indent = (task.indent or '') + indent_step
        for line in task.body.split('\n'):
            stripped = line.strip()
            new_nodes.append(RawLine(body_indent + stripped + '\n') if stripped else RawLine('\n'))
    for child in task.children:
        child_block = child_blocks.get(id(child)) or task_to_block(child)
        new_nodes.append(child_block)
    block.nodes[:] = new_nodes


def task_to_block(task: Task) -> TaskBlock:
    """Build a TaskBlock tree from a Task (with body string and children list)."""
    indent_step = get_indent_step()
    nodes = []
    if task.body:
        body_indent = (task.indent or '') + indent_step
        for line in task.body.split('\n'):
            stripped = line.strip()
            nodes.append(RawLine(body_indent + stripped + '\n') if stripped else RawLine('\n'))
    for child in task.children:
        if not child.indent:
            child.indent = (task.indent or '') + indent_step
        nodes.append(task_to_block(child))
    return TaskBlock(task=task, header=task.to_line() + '\n', nodes=nodes)


def move_task_week(state: WeekState, src_col: int, dst_col: int, cursor_row: int) -> int:
    src_cache = state.day(src_col)
    dst_cache = state.day(dst_col)
    src_tasks = src_cache.task_list
    if not src_tasks or not (0 <= cursor_row < len(src_tasks)):
        return cursor_row
    task = src_tasks.pop(cursor_row)
    dst_cache.task_list.append(task)
    block = src_cache.find_block(task)
    if block:
        remove_block(src_cache.nodes, block)
        append_block(dst_cache.nodes, block)
        if task.time:
            sort_timed_nodes(dst_cache.nodes)
    return len(dst_cache.task_list) - 1


def shift_task(state: WeekState, cursor_col: int, cursor_row: int, direction: int) -> tuple[int, int, int]:
    """Move the task under the cursor left (direction=-1) or right (+1).

    Returns (new_col, new_row, week_exit) where week_exit is 0 while still in
    the current week, or ±1 when the task crosses into an adjacent week.
    """
    tasks = state.day(cursor_col).task_list
    exp = week_expanded(tasks)
    if cursor_row >= len(exp):
        return cursor_col, cursor_row, 0
    root = root_task(exp[cursor_row])
    root_idx = tasks.index(root)
    dst_col = cursor_col + direction
    if 0 <= dst_col <= 6:
        move_task_week(state, cursor_col, dst_col, root_idx)
        new_exp = week_expanded(state.day(dst_col).task_list)
        new_row = next((i for i, t in enumerate(new_exp) if t is root), 0)
        return dst_col, new_row, 0
    else:
        edge_day = state.week_days[0 if direction == -1 else 6]
        adj_day = edge_day + datetime.timedelta(days=direction)
        ensure_day_loaded(state.cache, adj_day, state.directory)
        src_cache = state.day(cursor_col)
        adj_cache = state.cache[adj_day.isoformat()]
        tasks.pop(root_idx)
        block = src_cache.find_block(root)
        if block:
            remove_block(src_cache.nodes, block)
            append_block(adj_cache.nodes, block)
        adj_cache.task_list.append(root)
        adj_exp = week_expanded(adj_cache.task_list)
        new_row = next((i for i, t in enumerate(adj_exp) if t is root), len(adj_exp) - 1)
        return cursor_col, new_row, direction
