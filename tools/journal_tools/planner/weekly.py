import datetime
import os

from config import get_indent_step
from models import Task, get_minutes
from os_utils import BackupManager, FileFinder, FileWriter
from parser.file_model import RawLine, TaskBlock, parse, serialize
from .state import DayCache, WeekState
from .utils import week_expanded

DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']


def ensure_day_loaded(cache: dict, day: datetime.date, directory: str) -> DayCache:
    key = day.isoformat()
    if key not in cache:
        files = FileFinder.find_journal_files(directory, date_from=day, date_to=day)
        if files:
            nodes = parse(files[0])
            with open(files[0], 'r', encoding='utf-8') as f:
                original_content = f.read()
            cache[key] = DayCache(
                file_path=files[0],
                nodes=nodes,
                original_content=original_content,
            )
        else:
            cache[key] = DayCache(
                file_path=None,
                nodes=[],
                original_content='',
            )
    return cache[key]


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


def _find_path_for_task(nodes: list, task: Task) -> 'tuple[TaskBlock, list[tuple[list, int]]] | None':
    """Find task's block and return (block, path) where path is [(container, idx), ...]
    from the root nodes down; the last element is the block's direct container location."""
    for i, node in enumerate(nodes):
        if isinstance(node, TaskBlock):
            if node.task is task:
                return node, [(nodes, i)]
            result = _find_path_for_task(node.nodes, task)
            if result is not None:
                block, path = result
                return block, [(nodes, i)] + path
    return None


def _reindent_block(block: TaskBlock, new_indent: str) -> None:
    """Recursively update task.indent and RawLine body indents for a block tree."""
    indent_step = get_indent_step()
    old_body_indent = block.task.indent + indent_step
    new_body_indent = new_indent + indent_step
    block.task.indent = new_indent
    block.refresh_header()
    for node in block.nodes:
        if isinstance(node, RawLine) and node.raw.strip():
            if node.raw.startswith(old_body_indent):
                node.raw = new_body_indent + node.raw[len(old_body_indent):]
        elif isinstance(node, TaskBlock):
            _reindent_block(node, new_body_indent)


def tab_task(nodes: list, task: Task) -> bool:
    """Indent task under the preceding sibling, making it a subtask. Returns True if moved."""
    result = _find_path_for_task(nodes, task)
    if result is None:
        return False
    block, path = result
    container, idx = path[-1]
    prev_block = next(
        (container[i] for i in range(idx - 1, -1, -1) if isinstance(container[i], TaskBlock)),
        None,
    )
    if prev_block is None:
        return False
    container.pop(idx)
    _reindent_block(block, prev_block.task.indent + get_indent_step())
    prev_block.nodes.append(block)
    return True


def shift_tab_task(nodes: list, task: Task) -> bool:
    """Dedent task, promoting it to a sibling placed after its parent. Returns True if moved."""
    result = _find_path_for_task(nodes, task)
    if result is None or len(result[1]) < 2:
        return False
    block, path = result
    container, idx = path[-1]
    grandparent_container, parent_idx = path[-2]
    parent_block = grandparent_container[parent_idx]
    container.pop(idx)
    grandparent_container.insert(parent_idx + 1, block)
    _reindent_block(block, parent_block.task.indent)
    return True


def move_block_in_nodes(nodes: list, task: Task, direction: int) -> bool:
    """Swap an untimed task's block with the adjacent untimed sibling in direction (+1 down, -1 up).
    Timed siblings are skipped. Returns True if the swap happened."""
    result = _find_path_for_task(nodes, task)
    if result is None:
        return False
    block, path = result
    if block.task.time:
        return False
    container, idx = path[-1]
    if direction > 0:
        target_idx = next(
            (i for i in range(idx + 1, len(container))
             if isinstance(container[i], TaskBlock) and not container[i].task.time),
            None,
        )
    else:
        target_idx = next(
            (i for i in range(idx - 1, -1, -1)
             if isinstance(container[i], TaskBlock) and not container[i].task.time),
            None,
        )
    if target_idx is None:
        return False
    container[idx], container[target_idx] = container[target_idx], container[idx]
    return True


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


def task_to_block(task: Task, body: str | None = None, subtask_blocks: list | None = None) -> TaskBlock:
    """Build a TaskBlock from a Task, an optional body string, and optional child blocks."""
    indent_step = get_indent_step()
    nodes = []
    if body:
        body_indent = (task.indent or '') + indent_step
        for line in body.split('\n'):
            stripped = line.strip()
            nodes.append(RawLine(body_indent + stripped + '\n') if stripped else RawLine('\n'))
    for child_block in (subtask_blocks or []):
        if not child_block.task.indent:
            child_block.task.indent = (task.indent or '') + indent_step
        child_block.refresh_header()
        nodes.append(child_block)
    return TaskBlock(task=task, header=task.to_line() + '\n', nodes=nodes)


def move_task_week(state: WeekState, src_col: int, dst_col: int, cursor_row: int) -> int:
    src_cache = state.day(src_col)
    dst_cache = state.day(dst_col)
    src_blocks = src_cache.task_list
    if not src_blocks or not (0 <= cursor_row < len(src_blocks)):
        return cursor_row
    block = src_blocks[cursor_row]
    remove_block(src_cache.nodes, block)
    append_block(dst_cache.nodes, block)
    if block.task.time:
        sort_timed_nodes(dst_cache.nodes)
    return len(dst_cache.task_list) - 1


def shift_task(state: WeekState, cursor_col: int, cursor_row: int, direction: int) -> tuple[int, int, int]:
    """Move the task under the cursor left (direction=-1) or right (+1).

    Returns (new_col, new_row, week_exit) where week_exit is 0 while still in
    the current week, or ±1 when the task crosses into an adjacent week.
    """
    task_blocks = state.day(cursor_col).task_list
    exp = week_expanded(task_blocks)
    if cursor_row >= len(exp):
        return cursor_col, cursor_row, 0
    # Find depth-0 ancestor of the cursor position
    root_row = cursor_row
    while root_row > 0 and exp[root_row][1] > 0:
        root_row -= 1
    root_task_obj = exp[root_row][0]
    root_block = next(b for b in task_blocks if b.task is root_task_obj)
    root_idx = task_blocks.index(root_block)
    dst_col = cursor_col + direction
    if 0 <= dst_col <= 6:
        move_task_week(state, cursor_col, dst_col, root_idx)
        new_exp = week_expanded(state.day(dst_col).task_list)
        new_row = next((i for i, (t, _d) in enumerate(new_exp) if t is root_task_obj), 0)
        return dst_col, new_row, 0
    else:
        edge_day = state.week_days[0 if direction == -1 else 6]
        adj_day = edge_day + datetime.timedelta(days=direction)
        ensure_day_loaded(state.cache, adj_day, state.directory)
        src_cache = state.day(cursor_col)
        adj_cache = state.cache[adj_day.isoformat()]
        remove_block(src_cache.nodes, root_block)
        append_block(adj_cache.nodes, root_block)
        adj_exp = week_expanded(adj_cache.task_list)
        new_row = next((i for i, (t, _d) in enumerate(adj_exp) if t is root_task_obj), len(adj_exp) - 1)
        return cursor_col, new_row, direction
