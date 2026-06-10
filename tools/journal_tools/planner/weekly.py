import datetime
import os

from models import Task, top_level_tasks, get_minutes
from os_utils import BackupManager, FileFinder, FileWriter, task_block_end
from parser import TaskParser
from .state import DayCache, WeekState
from .utils import flatten_tasks, task_to_lines, root_task, week_expanded

DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']


def ensure_day_loaded(cache: dict, day: datetime.date, directory: str) -> DayCache:
    key = day.isoformat()
    if key not in cache:
        files = FileFinder.find_journal_files(directory, date_from=day, date_to=day)
        if files:
            all_tasks = TaskParser.parse_file(files[0])
            tl = list(top_level_tasks(all_tasks))
            cache[key] = DayCache(
                file_path=files[0],
                all_tasks=all_tasks,
                task_list=tl,
                original_task_list=list(tl),
                original_lines={t.line_number: t.to_line() for t in all_tasks},
                original_bodies={
                    t.line_number: t.body for t in all_tasks if t.line_number > 0
                },
            )
        else:
            cache[key] = DayCache(
                file_path=None,
                all_tasks=[],
                task_list=[],
                original_task_list=[],
                original_lines={},
                original_bodies={},
            )
    return cache[key]


def reload_day_in_cache(cache: dict, day: datetime.date, directory: str) -> None:
    """Re-parse a day's file and replace its cache entry with a fresh baseline."""
    key = day.isoformat()
    files = FileFinder.find_journal_files(directory, date_from=day, date_to=day)
    if files:
        all_tasks = TaskParser.parse_file(files[0])
        tl = list(top_level_tasks(all_tasks))
        cache[key] = DayCache(
            file_path=files[0],
            all_tasks=all_tasks,
            task_list=tl,
            original_task_list=list(tl),
            original_lines={t.line_number: t.to_line() for t in all_tasks},
            original_bodies={
                t.line_number: t.body for t in all_tasks if t.line_number > 0
            },
        )
    else:
        cache[key] = DayCache(None, [], [], [], {}, {})


def cache_has_changes(cache: dict) -> bool:
    for day in cache.values():
        if day.moved_subtasks or day.deleted_tasks:
            return True
        current_ids = {id(t) for t in day.task_list}
        orig_ids = {id(t) for t in day.original_task_list}
        if current_ids != orig_ids:
            return True
        for task in flatten_tasks(day.original_task_list):
            if task.line_number > 0 and day.original_lines.get(task.line_number) != task.to_line():
                return True
    return False


def _refresh_line_numbers(cache: dict, backed_up: set) -> None:
    """Re-parse modified files and update in-memory line numbers to match.

    Tasks moved between days retain stale line_numbers from their source file;
    updating them here ensures the next save's status-change pass writes to the
    correct lines.
    """
    for key, day in cache.items():
        if not day.file_path or day.file_path not in backed_up:
            continue
        if not os.path.exists(day.file_path):
            continue
        try:
            fresh = TaskParser.parse_file(day.file_path)
            ln_by_content: dict[str, int] = {}
            for t in flatten_tasks(fresh):
                ln_by_content.setdefault(t.to_line(), t.line_number)
            for task in flatten_tasks(day.task_list):
                new_ln = ln_by_content.get(task.to_line())
                if new_ln is not None:
                    task.line_number = new_ln
            day.original_lines = {t.line_number: t.to_line() for t in flatten_tasks(fresh)}
        except Exception:
            pass


def save_cache(cache: dict, directory: str) -> None:
    """Write all pending changes from the cache to disk (no prompt)."""
    backed_up: set = set()
    dst_keys_written: set = set()

    # Write new in-session tasks before any removals so they land at current line numbers.
    for key, day in cache.items():
        new_tasks = [t for t in day.task_list if t.line_number == -1]
        if not new_tasks:
            continue
        if day.file_path is None:
            day.file_path = os.path.join(directory, f"{key}.md")
            with open(day.file_path, 'w', encoding='utf-8'):
                pass
        if day.file_path not in backed_up:
            BackupManager.backup(day.file_path, directory)
            backed_up.add(day.file_path)
        for task in new_tasks:
            FileWriter.paste_task(day.file_path, task_to_lines(task))

    # Build reverse lookup: id(task) -> date key (where the task currently lives).
    task_location: dict = {id(t): key for key, day in cache.items() for t in day.task_list}

    # Write status changes to each task's original file before cutting any tasks,
    # so blocks that are about to move carry their updated status.
    for key, day in cache.items():
        if not day.file_path:
            continue
        status_changed = [
            t for t in flatten_tasks(day.original_task_list)
            if t.line_number > 0
            and day.original_lines.get(t.line_number) != t.to_line()
        ]
        if not status_changed:
            continue
        if day.file_path not in backed_up:
            BackupManager.backup(day.file_path, directory)
            backed_up.add(day.file_path)
        with open(day.file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        for task in status_changed:
            if 0 < task.line_number <= len(lines):
                lines[task.line_number - 1] = task.to_line() + '\n'
        FileWriter.write_atomic(day.file_path, lines)

    # Remove deleted tasks.
    for key, day in cache.items():
        if not day.deleted_tasks or not day.file_path:
            continue
        if day.file_path not in backed_up:
            BackupManager.backup(day.file_path, directory)
            backed_up.add(day.file_path)
        with open(day.file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        all_lns = sorted(day.original_lines.keys())
        to_remove: set = set()
        for task in day.deleted_tasks:
            if task.line_number <= 0:
                continue
            task_indent = len(task.indent)
            block_end = all_lns[-1] if all_lns else task.line_number
            found = False
            for ln in all_lns:
                if found:
                    orig = day.original_lines[ln]
                    if len(orig) - len(orig.lstrip()) <= task_indent:
                        block_end = ln - 1
                        break
                elif ln == task.line_number:
                    found = True
            to_remove.update(range(task.line_number, block_end + 1))
        FileWriter.write_atomic(day.file_path, [ln for i, ln in enumerate(lines, 1) if i not in to_remove])
        day.deleted_tasks.clear()

    # Collect all line removals in one pass before applying any of them.
    # Applying removals sequentially would shift line numbers and corrupt later reads.
    src_lines: dict = {}

    def _read_src(path):
        if path not in src_lines:
            with open(path, 'r', encoding='utf-8') as f:
                src_lines[path] = f.readlines()
        return src_lines[path]

    remove_set: dict = {}  # file_path -> set of 1-based line numbers to remove
    pastes: list = []      # (dst_key, dst_path, block) to paste after removals

    for key, day in cache.items():
        if not day.moved_subtasks or not day.file_path:
            continue
        lines = _read_src(day.file_path)
        rs = remove_set.setdefault(day.file_path, set())
        for subtask in day.moved_subtasks:
            for t in flatten_tasks([subtask]):
                if 0 < t.line_number <= len(lines):
                    rs.add(t.line_number)
                for ln in t.body_line_numbers:
                    if 0 < ln <= len(lines):
                        rs.add(ln)
        day.moved_subtasks.clear()

    for key, day in cache.items():
        if not day.file_path:
            continue
        current_ids = {id(t) for t in day.task_list}
        departed = [
            (t, task_location.get(id(t)))
            for t in day.original_task_list
            if id(t) not in current_ids
        ]
        departed = [(t, dst) for t, dst in departed if dst is not None and dst != key]
        if not departed:
            continue

        lines = _read_src(day.file_path)
        sorted_all = sorted(day.all_tasks, key=lambda t: t.line_number)
        rs = remove_set.setdefault(day.file_path, set())

        for task, dst_key in departed:
            start = task.line_number - 1
            end = task_block_end(task, sorted_all, len(lines))
            block = lines[start:end]
            rs.update(range(start + 1, end + 1))  # 1-based

            dst_day = cache[dst_key]
            if dst_day.file_path is None:
                dst_path = os.path.join(directory, f"{dst_key}.md")
                with open(dst_path, 'w'):
                    pass
                dst_day.file_path = dst_path
            pastes.append((dst_key, dst_day.file_path, block))

    # Apply all removals, then paste moved blocks and sort their destinations.
    for file_path, ln_set in remove_set.items():
        if not ln_set:
            continue
        if file_path not in backed_up:
            BackupManager.backup(file_path, directory)
            backed_up.add(file_path)
        lines = _read_src(file_path)
        remaining = [line for i, line in enumerate(lines, 1) if i not in ln_set]
        FileWriter.write_atomic(file_path, remaining)

    for dst_key, dst_path, block in pastes:
        if dst_path not in backed_up:
            BackupManager.backup(dst_path, directory)
            backed_up.add(dst_path)
        FileWriter.paste_task(dst_path, block)
        dst_keys_written.add(dst_key)

    for dst_key in dst_keys_written:
        path = cache[dst_key].file_path
        if path and os.path.exists(path):
            all_tasks = TaskParser.parse_file(path)
            timed = [t for t in all_tasks if t.time is not None and t.parent is None]
            FileWriter.sort_timed_tasks(path, timed, all_tasks)

    _refresh_line_numbers(cache, backed_up)

    # Reset the baseline so these changes aren't re-detected on the next save.
    for day in cache.values():
        day.original_task_list = list(day.task_list)


def move_task_week(state: WeekState, src_col: int, dst_col: int, cursor_row: int) -> int:
    src_tasks = state.day(src_col).task_list
    if not src_tasks or not (0 <= cursor_row < len(src_tasks)):
        return cursor_row
    task = src_tasks.pop(cursor_row)
    state.day(dst_col).task_list.append(task)
    return len(state.day(dst_col).task_list) - 1


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
        tasks.pop(root_idx)
        state.cache[adj_day.isoformat()].task_list.append(root)
        adj_exp = week_expanded(state.cache[adj_day.isoformat()].task_list)
        new_row = next((i for i, t in enumerate(adj_exp) if t is root), len(adj_exp) - 1)
        return cursor_col, new_row, direction
