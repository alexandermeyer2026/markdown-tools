import datetime
import os
import shutil
import sys
import termios
import tty
from dataclasses import dataclass, field

from models import Task, TaskTime, top_level_tasks
from os_utils import BackupManager, FileFinder, FileWriter, resolve_date
from parser import TaskParser
from tools.journal_tools.rendering import (
    STATUS_ICONS, STATUS_COLORS, BOLD, GRAY, RESET,
    get_minutes, get_time_slot, minutes_to_time,
    scale_lines, subtask_rows, ansi_truncate_pad,
)


@dataclass
class DayCache:
    file_path: str | None
    all_tasks: list          # original flat parse (for cut operations)
    task_list: list          # current top-level tasks (mutable, shared with WeekState)
    original_task_list: list # snapshot at load time (for change detection)
    original_lines: dict     # {line_number: original to_line()} for status detection
    new_tasks: list = field(default_factory=list)       # tasks created in-session (no line number)
    moved_subtasks: list = field(default_factory=list)  # subtasks removed from parents in this day


@dataclass
class WeekState:
    week_days: list
    week_tasks: list         # list references into cache DayCache.task_list
    file_paths: list
    all_tasks_per_day: list
    directory: str
    cache: dict              # date ISO string -> DayCache


class PlannerTool:
    STEP_SIZE_HOURS = 0.25  # 15-minute steps

    @staticmethod
    def run(args, directory='.'):
        if not args:
            print("Usage: journal planner <today|yesterday|tomorrow|YYYY-MM-DD|week|file>")
            return

        if args[0].lower() == 'week':
            PlannerTool.run_week(directory)
            return

        input_arg = args[0]
        basename = os.path.basename(input_arg)

        date = resolve_date(basename) or FileFinder.get_journal_file_date(input_arg)

        if date:
            directory = os.path.dirname(input_arg) or directory
            journal_files = FileFinder.find_journal_files(directory, date_from=date, date_to=date)
            if not journal_files:
                print(f"No journal file for {date} found")
                return
            file_path = journal_files[0]
        else:
            if not os.path.exists(input_arg):
                print(f"File {input_arg} does not exist")
                return
            file_path = input_arg

        tasks = TaskParser.parse_file(file_path)
        PlannerTool.interactive_plan(directory, file_path, tasks, date=date)

    # ── Utilities ─────────────────────────────────────────────────────────────

    @staticmethod
    def read_key() -> str:
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
            if not ch:
                raise EOFError("stdin closed")
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
        return ch

    # ── Rendering ─────────────────────────────────────────────────────────────

    @staticmethod
    def _task_row(task: Task, step_size_hours: float, first_slot: int, is_selected: bool) -> str:
        icon  = STATUS_ICONS.get(task.status, '?')
        color = STATUS_COLORS.get(task.status, GRAY)

        if task.time:
            label = f" {color}{icon}{RESET} {BOLD}{task.title}{RESET}"
            start_m = get_minutes(task.time.start)
            start_slot = end_slot = get_time_slot(start_m, step_size_hours)
            if task.time.end:
                end_m = get_minutes(task.time.end)
                end_slot = get_time_slot(end_m - 1, step_size_hours)
            bar = color + '█' * max(end_slot - start_slot + 1, 1) + RESET
            offset = start_slot - first_slot
            if is_selected:
                pre = ' ' * max(offset - 2, 0) + f'\x1b[7m>\x1b[0m '
            else:
                pre = ' ' * offset
            return '  ' + pre + bar + f" {task.time.to_str()}" + label
        else:
            label = f" {color}{icon}{RESET} {BOLD}{task.title}{RESET}"
            prefix = f'\x1b[7m>{RESET} ' if is_selected else '  '
            return prefix + label.lstrip()

    @staticmethod
    def _icon_col(task: Task, step_size_hours: float, first_slot: int) -> int:
        if not task.time:
            return 2  # '  ' prefix
        start_m = get_minutes(task.time.start)
        start_slot = get_time_slot(start_m, step_size_hours)
        end_slot = start_slot
        if task.time.end:
            end_slot = get_time_slot(get_minutes(task.time.end) - 1, step_size_hours)
        bar_width = max(end_slot - start_slot + 1, 1)
        return 2 + (start_slot - first_slot) + bar_width + 1 + len(task.time.to_str()) + 1

    @staticmethod
    def _flatten_tasks(tasks: list) -> list:
        result = []
        for task in tasks:
            result.append(task)
            result.extend(PlannerTool._flatten_tasks(task.children))
        return result

    @staticmethod
    def _task_to_lines(task: Task) -> list[str]:
        lines = [task.to_line() + '\n']
        for child in task.children:
            lines.extend(PlannerTool._task_to_lines(child))
        return lines

    @staticmethod
    def _week_expanded(tasks: list) -> list[Task]:
        """Flatten top-level tasks and all their descendants for week display, timed first."""
        timed = sorted([t for t in tasks if t.time], key=lambda t: get_minutes(t.time.start))
        untimed = [t for t in tasks if not t.time]
        result = []
        for task in timed + untimed:
            result.append(task)
            result.extend(PlannerTool._flatten_tasks(task.children))
        return result

    @staticmethod
    def _root_task(task: Task) -> Task:
        while task.parent is not None:
            task = task.parent
        return task

    @staticmethod
    def render(file_path, timed_tasks, untimed_tasks, selected_task,
               step_size_hours, directory, has_changes, date):
        lines = []

        rel_path = os.path.relpath(file_path, directory)
        marker = ' *' if has_changes else ''
        lines.append(f"  {BOLD}Planning: {rel_path}{marker}{RESET}\n")

        if timed_tasks:
            first_slot = 0

            now_slot = None
            if date and date == datetime.date.today():
                now_m    = datetime.datetime.now().hour * 60 + datetime.datetime.now().minute
                now_slot = get_time_slot(now_m, step_size_hours)

            hours_line, scale_line = scale_lines(step_size_hours, first_slot, now_slot)
            lines.append('  ' + hours_line)
            lines.append('  ' + scale_line)

            for task in timed_tasks:
                lines.append(PlannerTool._task_row(task, step_size_hours, first_slot, task is selected_task))
                lines.extend(subtask_rows(task, left_pad=PlannerTool._icon_col(task, step_size_hours, first_slot), selected_task=selected_task))
        else:
            lines.append(f"  {GRAY}No timed tasks yet{RESET}")

        if untimed_tasks:
            lines.append(f"\n  {GRAY}── Unscheduled {'─' * 50}{RESET}")
            for task in untimed_tasks:
                lines.append(PlannerTool._task_row(task, step_size_hours, 0, task is selected_task))
                lines.extend(subtask_rows(task, left_pad=PlannerTool._icon_col(task, step_size_hours, 0), selected_task=selected_task))

        if not timed_tasks and not untimed_tasks:
            lines.append(f"\n  {GRAY}No tasks. Press n to add one.{RESET}")

        lines.append(f"\n  {GRAY}[j/k] move  [h/l] shift  [H/L] end time  [r] remove time  [n] new  [t/i/d/f] status  [q] quit{RESET}")

        cols = shutil.get_terminal_size(fallback=(80, 24)).columns
        padded = [ansi_truncate_pad(line, cols) for line in '\n'.join(lines).split('\n')]
        sys.stdout.write('\x1b[?25l\x1b[H' + '\n'.join(padded) + '\x1b[J\x1b[?25h')
        sys.stdout.flush()

    # ── Week planner ──────────────────────────────────────────────────────────

    DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

    @staticmethod
    def _ensure_day_loaded(cache: dict, day: datetime.date, directory: str) -> DayCache:
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
                )
            else:
                cache[key] = DayCache(
                    file_path=None,
                    all_tasks=[],
                    task_list=[],
                    original_task_list=[],
                    original_lines={},
                )
        return cache[key]

    @staticmethod
    def _reload_day_in_cache(cache: dict, day: datetime.date, directory: str) -> None:
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
            )
        else:
            cache[key] = DayCache(None, [], [], [], {})

    @staticmethod
    def _cache_has_changes(cache: dict) -> bool:
        for day in cache.values():
            if day.new_tasks or day.moved_subtasks:
                return True
            current_ids = {id(t) for t in day.task_list}
            orig_ids = {id(t) for t in day.original_task_list}
            if current_ids != orig_ids:
                return True
            for task in PlannerTool._flatten_tasks(day.original_task_list):
                if task.line_number > 0 and day.original_lines.get(task.line_number) != task.to_line():
                    return True
        return False

    @staticmethod
    def _save_cache(cache: dict, directory: str) -> None:
        """Write all pending changes from the cache to disk (no prompt)."""
        backed_up: set = set()
        dst_keys_written: set = set()

        # Phase 0: new tasks — append to destination files before any removals.
        for key, day in cache.items():
            if not day.new_tasks:
                continue
            if day.file_path is None:
                day.file_path = os.path.join(directory, f"{key}.md")
                with open(day.file_path, 'w', encoding='utf-8'):
                    pass
            if day.file_path not in backed_up:
                BackupManager.backup(day.file_path, directory)
                backed_up.add(day.file_path)
            for task in day.new_tasks:
                FileWriter.paste_task(day.file_path, PlannerTool._task_to_lines(task))
            day.new_tasks.clear()

        # Build reverse lookup: id(task) -> date key (where the task currently lives)
        task_location: dict = {}
        for key, day in cache.items():
            for task in day.task_list:
                task_location[id(task)] = key

        # Phase 1: status changes — save to each task's ORIGINAL day before any cuts.
        # This includes tasks that will be moved away, so the cut block carries the new status.
        for key, day in cache.items():
            if not day.file_path:
                continue
            status_changed = [
                t for t in PlannerTool._flatten_tasks(day.original_task_list)
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
                lines[task.line_number - 1] = task.to_line() + '\n'
            FileWriter.write_atomic(day.file_path, lines)

        # Phase 1.5: remove carried-forward subtask lines from source files.
        for key, day in cache.items():
            if not day.moved_subtasks or not day.file_path:
                continue
            if day.file_path not in backed_up:
                BackupManager.backup(day.file_path, directory)
                backed_up.add(day.file_path)
            with open(day.file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            lines_to_remove: set[int] = set()
            for subtask in day.moved_subtasks:
                for t in PlannerTool._flatten_tasks([subtask]):
                    if 0 < t.line_number <= len(lines):
                        lines_to_remove.add(t.line_number)
            if lines_to_remove:
                remaining = [line for i, line in enumerate(lines, 1) if i not in lines_to_remove]
                FileWriter.write_atomic(day.file_path, remaining)
            day.moved_subtasks.clear()

        # Phase 2: task moves — cut from source files, paste to destination files.
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
            if day.file_path not in backed_up:
                BackupManager.backup(day.file_path, directory)
                backed_up.add(day.file_path)
            # Process in reverse line order so earlier line numbers stay valid
            departed.sort(key=lambda x: x[0].line_number, reverse=True)
            for task, dst_key in departed:
                dst_day = cache[dst_key]
                if dst_day.file_path is None:
                    dst_path = os.path.join(directory, f"{dst_key}.md")
                    with open(dst_path, 'w'):
                        pass
                    dst_day.file_path = dst_path
                if dst_day.file_path not in backed_up:
                    BackupManager.backup(dst_day.file_path, directory)
                    backed_up.add(dst_day.file_path)
                block = FileWriter.cut_task(day.file_path, task, day.all_tasks)
                FileWriter.paste_task(dst_day.file_path, block)
                dst_keys_written.add(dst_key)

        # Sort timed tasks in destination files
        for dst_key in dst_keys_written:
            path = cache[dst_key].file_path
            if path and os.path.exists(path):
                all_tasks = TaskParser.parse_file(path)
                timed = [t for t in all_tasks if t.time is not None and t.parent is None]
                FileWriter.sort_timed_tasks(path, timed, all_tasks)

        # Reset the baseline so changes aren't re-detected after this save
        for day in cache.values():
            day.original_task_list = list(day.task_list)

    @staticmethod
    def run_week(directory='.'):
        today = datetime.date.today()
        week_offset = 0
        start_col = today.weekday()
        start_row = 0
        cache: dict = {}

        while True:
            monday = today - datetime.timedelta(days=today.weekday()) + datetime.timedelta(weeks=week_offset)
            week_days = [monday + datetime.timedelta(days=i) for i in range(7)]

            for day in week_days:
                PlannerTool._ensure_day_loaded(cache, day, directory)

            state = WeekState(
                week_days=week_days,
                week_tasks=[cache[d.isoformat()].task_list for d in week_days],
                file_paths=[cache[d.isoformat()].file_path for d in week_days],
                all_tasks_per_day=[cache[d.isoformat()].all_tasks for d in week_days],
                directory=directory,
                cache=cache,
            )

            result, start_row = PlannerTool.interactive_week(state, start_col=start_col, start_row=start_row)

            if result == 0:
                if PlannerTool._cache_has_changes(cache):
                    sys.stdout.write('\x1b[2J\x1b[H')
                    sys.stdout.flush()
                    if input("Save changes? [y/n]: ").strip().lower() == 'y':
                        PlannerTool._save_cache(cache, directory)
                        print("✓ Changes saved")
                break

            week_offset += result
            start_col = 6 if result == -1 else 0

    @staticmethod
    def _week_cell(task: Task | None, col_width: int, is_selected: bool) -> str:
        prefix = '> ' if is_selected else '  '
        if task is None:
            text = prefix.ljust(col_width)
            return f'\x1b[7m{text}{RESET}' if is_selected else text
        icon = STATUS_ICONS.get(task.status, '?')
        if task.parent is not None:
            depth = 0
            p = task.parent
            while p is not None:
                depth += 1
                p = p.parent
            title_max = max(col_width - 4 - depth, 1)
            title_str = task.title[:title_max].ljust(title_max)
            if is_selected:
                return f'\x1b[7m> {" " * depth}{icon} {title_str}{RESET}'
            return f'  {" " * depth}{GRAY}{icon} {title_str}{RESET}'
        color     = STATUS_COLORS.get(task.status, GRAY)
        title_max = col_width - 4  # 2 prefix + 1 icon + 1 space
        title_str = task.title[:title_max].ljust(title_max)
        if is_selected:
            return f'\x1b[7m{prefix}{icon} {title_str}{RESET}'
        return f'{prefix}{color}{icon}{RESET} {title_str}'

    @staticmethod
    def render_week(state: WeekState, cursor_col: int, cursor_row: int):
        cols = shutil.get_terminal_size(fallback=(80, 24)).columns
        col_width = max((cols - 2) // 7, 10)
        margin = '  '
        today = datetime.date.today()

        lines = []
        monday, sunday = state.week_days[0], state.week_days[-1]
        lines.append(f"{margin}{BOLD}Week {monday.strftime('%b %d')} – {sunday.strftime('%b %d, %Y')}{RESET}\n")

        # Day headers
        header = margin
        for i, day in enumerate(state.week_days):
            label = f"{PlannerTool.DAY_NAMES[i]} {day.strftime('%m/%d')}"
            padded = label.ljust(col_width)
            if cursor_row == -1 and i == cursor_col:
                header += f"\x1b[7m{padded}{RESET}"
            elif day == today:
                header += f"{BOLD}{padded}{RESET}"
            else:
                header += padded
        lines.append(header)
        lines.append(margin + ('─' * (col_width - 1) + ' ') * 7)

        # Task rows — at least 1 row so the cursor is always visible
        expanded_per_col = [PlannerTool._week_expanded(state.week_tasks[i]) for i in range(7)]
        max_rows = max(max((len(e) for e in expanded_per_col), default=0), 1)
        for row in range(max_rows):
            line = margin
            for col_idx in range(7):
                exp = expanded_per_col[col_idx]
                is_selected = (col_idx == cursor_col and row == cursor_row)
                if row < len(exp):
                    line += PlannerTool._week_cell(exp[row], col_width, is_selected)
                elif is_selected:
                    line += PlannerTool._week_cell(None, col_width, True)
                else:
                    line += ' ' * col_width
            lines.append(line)

        lines.append(f"\n{margin}{GRAY}[h/j/k/l] navigate  [H/L] move task  [>] carry subtasks  [t/i/d/f] status  [Enter] open day  [q] quit{RESET}")

        padded = [ansi_truncate_pad(line, cols) for line in '\n'.join(lines).split('\n')]
        sys.stdout.write('\x1b[?25l\x1b[H' + '\n'.join(padded) + '\x1b[J\x1b[?25h')
        sys.stdout.flush()

    @staticmethod
    def _move_task_week(state: WeekState, src_col: int, dst_col: int, cursor_row: int) -> int:
        if not state.week_tasks[src_col] or not (0 <= cursor_row < len(state.week_tasks[src_col])):
            return cursor_row
        task = state.week_tasks[src_col].pop(cursor_row)
        state.week_tasks[dst_col].append(task)
        return len(state.week_tasks[dst_col]) - 1

    @staticmethod
    def interactive_week(state: WeekState, start_col: int | None = None, start_row: int = 0) -> tuple[int, int]:
        cursor_col = start_col if start_col is not None else next((i for i, t in enumerate(state.week_tasks) if t), 0)
        cursor_row = start_row

        while True:
            PlannerTool.render_week(state, cursor_col, cursor_row)
            key = PlannerTool.read_key()

            if key in ('q', '\x03'):
                return 0, 0

            elif key == '\r':
                if cursor_row == -1:
                    col = cursor_col
                    day = state.week_days[col]
                    day_key = day.isoformat()

                    # Save pending changes so the day planner reads up-to-date files
                    if PlannerTool._cache_has_changes(state.cache):
                        PlannerTool._save_cache(state.cache, state.directory)

                    # Reload the target day (file may have been created by _save_cache)
                    PlannerTool._reload_day_in_cache(state.cache, day, state.directory)

                    fp = state.cache[day_key].file_path
                    if fp is None:
                        fp = os.path.join(state.directory, day.strftime('%Y-%m-%d.md'))
                        open(fp, 'w').close()
                        PlannerTool._reload_day_in_cache(state.cache, day, state.directory)
                        fp = state.cache[day_key].file_path

                    tasks = TaskParser.parse_file(fp)
                    PlannerTool.interactive_plan(state.directory, fp, tasks, date=day)

                    # Reload the day after the day planner closes
                    PlannerTool._reload_day_in_cache(state.cache, day, state.directory)
                    state.week_tasks[col] = state.cache[day_key].task_list
                    state.file_paths[col] = state.cache[day_key].file_path
                    state.all_tasks_per_day[col] = state.cache[day_key].all_tasks

            elif key == 'j':
                if cursor_row == -1:
                    cursor_row = 0
                else:
                    exp = PlannerTool._week_expanded(state.week_tasks[cursor_col])
                    if exp:
                        cursor_row = min(cursor_row + 1, len(exp) - 1)

            elif key == 'k':
                cursor_row = max(cursor_row - 1, -1)

            elif key == 'h':
                if cursor_col == 0:
                    return -1, 0
                cursor_col -= 1
                if cursor_row >= 0:
                    exp = PlannerTool._week_expanded(state.week_tasks[cursor_col])
                    cursor_row = min(cursor_row, max(len(exp) - 1, 0))

            elif key == 'l':
                if cursor_col == 6:
                    return 1, 0
                cursor_col += 1
                if cursor_row >= 0:
                    exp = PlannerTool._week_expanded(state.week_tasks[cursor_col])
                    cursor_row = min(cursor_row, max(len(exp) - 1, 0))

            elif key in ('t', 'i', 'd', 'f') and cursor_row >= 0:
                exp = PlannerTool._week_expanded(state.week_tasks[cursor_col])
                if cursor_row < len(exp):
                    exp[cursor_row].status = {'t': 'todo', 'i': 'in progress', 'd': 'done', 'f': 'failed'}[key]

            elif key == 'H' and cursor_row >= 0 and state.week_tasks[cursor_col]:
                exp = PlannerTool._week_expanded(state.week_tasks[cursor_col])
                if cursor_row < len(exp):
                    root = PlannerTool._root_task(exp[cursor_row])
                    root_idx = state.week_tasks[cursor_col].index(root)
                    if cursor_col > 0:
                        PlannerTool._move_task_week(state, cursor_col, cursor_col - 1, root_idx)
                        cursor_col -= 1
                        new_exp = PlannerTool._week_expanded(state.week_tasks[cursor_col])
                        cursor_row = next((i for i, t in enumerate(new_exp) if t is root), 0)
                    else:
                        prev_day = state.week_days[0] - datetime.timedelta(days=1)
                        PlannerTool._ensure_day_loaded(state.cache, prev_day, state.directory)
                        state.week_tasks[cursor_col].pop(root_idx)
                        state.cache[prev_day.isoformat()].task_list.append(root)
                        prev_exp = PlannerTool._week_expanded(state.cache[prev_day.isoformat()].task_list)
                        new_row = next((i for i, t in enumerate(prev_exp) if t is root), len(prev_exp) - 1)
                        return -1, new_row

            elif key == 'L' and cursor_row >= 0 and state.week_tasks[cursor_col]:
                exp = PlannerTool._week_expanded(state.week_tasks[cursor_col])
                if cursor_row < len(exp):
                    root = PlannerTool._root_task(exp[cursor_row])
                    root_idx = state.week_tasks[cursor_col].index(root)
                    if cursor_col < 6:
                        PlannerTool._move_task_week(state, cursor_col, cursor_col + 1, root_idx)
                        cursor_col += 1
                        new_exp = PlannerTool._week_expanded(state.week_tasks[cursor_col])
                        cursor_row = next((i for i, t in enumerate(new_exp) if t is root), 0)
                    else:
                        next_day = state.week_days[6] + datetime.timedelta(days=1)
                        PlannerTool._ensure_day_loaded(state.cache, next_day, state.directory)
                        state.week_tasks[cursor_col].pop(root_idx)
                        state.cache[next_day.isoformat()].task_list.append(root)
                        next_exp = PlannerTool._week_expanded(state.cache[next_day.isoformat()].task_list)
                        new_row = next((i for i, t in enumerate(next_exp) if t is root), len(next_exp) - 1)
                        return 1, new_row

            elif key == '>' and cursor_row >= 0:
                exp = PlannerTool._week_expanded(state.week_tasks[cursor_col])
                if cursor_row < len(exp):
                    task = exp[cursor_row]
                    if task.parent is None:
                        unfinished = [c for c in task.children if c.status not in ('done', 'failed')]
                        if unfinished:
                            task.children = [c for c in task.children if c.status in ('done', 'failed')]
                            day_key = state.week_days[cursor_col].isoformat()
                            state.cache[day_key].moved_subtasks.extend(unfinished)
                            tomorrow = state.week_days[cursor_col] + datetime.timedelta(days=1)
                            PlannerTool._ensure_day_loaded(state.cache, tomorrow, state.directory)
                            new_task = Task(
                                title=task.title,
                                status='todo',
                                time=None,
                                line_number=-1,
                                indent='',
                                children=list(unfinished),
                            )
                            for child in unfinished:
                                child.parent = new_task
                            tomorrow_key = tomorrow.isoformat()
                            state.cache[tomorrow_key].task_list.append(new_task)
                            state.cache[tomorrow_key].new_tasks.append(new_task)

    # ── Persistence ───────────────────────────────────────────────────────────

    @staticmethod
    def _has_changes(timed_tasks, untimed_tasks, original_lines, new_tasks) -> bool:
        if new_tasks:
            return True
        for task in PlannerTool._flatten_tasks(timed_tasks + untimed_tasks):
            if task.line_number > 0 and task.line_number in original_lines:
                if original_lines[task.line_number] != task.to_line():
                    return True
        return False

    @staticmethod
    def _save(file_path, directory, timed_tasks, untimed_tasks, original_lines, new_tasks):
        BackupManager.backup(file_path, directory)

        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        for task in PlannerTool._flatten_tasks(timed_tasks + untimed_tasks):
            if task.line_number in original_lines and original_lines[task.line_number] != task.to_line():
                lines[task.line_number - 1] = task.to_line() + '\n'

        for task in new_tasks:
            if lines:
                lines.append('\n')
            lines.append(task.to_line() + '\n')

        FileWriter.write_atomic(file_path, lines)

        all_tasks = TaskParser.parse_file(file_path)
        timed = [t for t in all_tasks if t.time is not None and t.parent is None]
        FileWriter.sort_timed_tasks(file_path, timed, all_tasks)

    # ── Main loop ─────────────────────────────────────────────────────────────

    @staticmethod
    def interactive_plan(directory, file_path, tasks, date=None):
        step   = PlannerTool.STEP_SIZE_HOURS
        step_m = int(step * 60)

        timed_tasks   = sorted([t for t in tasks if t.time and t.parent is None],
                               key=lambda t: get_minutes(t.time.start))
        untimed_tasks = [t for t in tasks if not t.time and t.parent is None]
        new_tasks     = []

        original_lines = {t.line_number: t.to_line() for t in tasks if t.line_number > 0}
        cursor_idx = 0

        while True:
            navigable   = PlannerTool._flatten_tasks(timed_tasks + untimed_tasks)
            selected    = navigable[cursor_idx] if navigable else None
            has_changes = PlannerTool._has_changes(timed_tasks, untimed_tasks, original_lines, new_tasks)
            PlannerTool.render(file_path, timed_tasks, untimed_tasks, selected,
                               step, directory, has_changes, date)

            key = PlannerTool.read_key()

            if key in ('q', '\x03'):  # q or Ctrl+C
                if has_changes:
                    sys.stdout.write('\x1b[2J\x1b[H')
                    sys.stdout.flush()
                    confirm = input("Save changes? [y/n]: ").strip().lower()
                    if confirm == 'y':
                        PlannerTool._save(file_path, directory, timed_tasks,
                                          untimed_tasks, original_lines, new_tasks)
                        print(f"✓ Changes saved")
                break

            elif key == 'j':
                if navigable:
                    cursor_idx = min(cursor_idx + 1, len(navigable) - 1)

            elif key == 'k':
                cursor_idx = max(cursor_idx - 1, 0)

            elif key in ('h', 'l'):
                if not navigable or selected.parent is not None:
                    continue
                direction = -1 if key == 'h' else 1

                if selected.time is None:
                    selected.time = TaskTime(start='12:00')
                    untimed_tasks.remove(selected)
                    timed_tasks.append(selected)
                    timed_tasks.sort(key=lambda t: get_minutes(t.time.start))
                else:
                    start_m = get_minutes(selected.time.start)
                    if selected.time.end:
                        end_m    = get_minutes(selected.time.end)
                        duration = end_m - start_m
                        new_start = max(0, min(start_m + direction * step_m, 24 * 60 - duration))
                        selected.time = TaskTime(
                            start=minutes_to_time(new_start),
                            end=minutes_to_time(new_start + duration),
                        )
                    else:
                        new_start = max(0, min(start_m + direction * step_m, 23 * 60 + 45))
                        selected.time = TaskTime(start=minutes_to_time(new_start))
                    timed_tasks.sort(key=lambda t: get_minutes(t.time.start))
                navigable  = PlannerTool._flatten_tasks(timed_tasks + untimed_tasks)
                cursor_idx = next(i for i, t in enumerate(navigable) if t is selected)

            elif key == 'H':  # shrink: move end time earlier
                if not navigable or selected.parent is not None:
                    continue
                if selected.time and selected.time.end:
                    start_m = get_minutes(selected.time.start)
                    end_m   = get_minutes(selected.time.end)
                    new_end = end_m - step_m
                    if new_end > start_m:
                        selected.time = TaskTime(start=selected.time.start,
                                                 end=minutes_to_time(new_end))
                    else:
                        selected.time = TaskTime(start=selected.time.start)

            elif key == 'L':  # extend: move end time later
                if not navigable or selected.parent is not None:
                    continue
                if selected.time:
                    if selected.time.end:
                        new_end = min(get_minutes(selected.time.end) + step_m, 24 * 60)
                    else:
                        new_end = min(get_minutes(selected.time.start) + step_m, 24 * 60)
                    selected.time = TaskTime(start=selected.time.start,
                                             end=minutes_to_time(new_end))

            elif key in ('t', 'i', 'd', 'f'):
                if selected:
                    selected.status = {'t': 'todo', 'i': 'in progress', 'd': 'done', 'f': 'failed'}[key]

            elif key == 'r':
                if navigable and selected.parent is None:
                    if selected.time and selected in timed_tasks:
                        selected.time = None
                        timed_tasks.remove(selected)
                        untimed_tasks.insert(0, selected)
                        cursor_idx = min(cursor_idx, len(PlannerTool._flatten_tasks(timed_tasks + untimed_tasks)) - 1)

            elif key == 'n':
                sys.stdout.write('\x1b[2J\x1b[H')
                sys.stdout.flush()
                title = input("New task title: ").strip()
                if title:
                    new_task = Task(title=title, status='todo', time=None, line_number=-1, indent='')
                    untimed_tasks.append(new_task)
                    new_tasks.append(new_task)
                    cursor_idx = len(PlannerTool._flatten_tasks(timed_tasks + untimed_tasks)) - 1
