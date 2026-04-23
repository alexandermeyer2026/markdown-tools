import datetime
import os
import re
import shutil
import sys
import termios
import tty

from models import Task, TaskTime
from os_utils import BackupManager, FileFinder, FileWriter
from parser import TaskParser
from tools.journal_tools.rendering import (
    STATUS_ICONS, STATUS_COLORS, BOLD, GRAY, RESET,
    get_minutes, get_time_slot, minutes_to_time,
    scale_lines, subtask_rows, ansi_truncate_pad,
)


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

        if basename.lower() == 'today':
            date = datetime.date.today()
        elif basename.lower() == 'tomorrow':
            date = datetime.date.today() + datetime.timedelta(days=1)
        elif basename.lower() == 'yesterday':
            date = datetime.date.today() - datetime.timedelta(days=1)
        elif re.fullmatch(r'\d{4}-\d{2}-\d{2}', basename):
            date = datetime.datetime.strptime(basename, '%Y-%m-%d').date()
        else:
            date = FileFinder.get_journal_file_date(input_arg)

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

    get_minutes    = staticmethod(get_minutes)
    get_time_slot  = staticmethod(get_time_slot)
    minutes_to_time = staticmethod(minutes_to_time)

    @staticmethod
    def read_key() -> str:
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
            if ch == '\x1b':
                ch += sys.stdin.read(2)
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
    def render(file_path, timed_tasks, untimed_tasks, cursor_idx,
               step_size_hours, directory, has_changes, date):
        lines = []

        rel_path = os.path.relpath(file_path, directory)
        marker = ' *' if has_changes else ''
        lines.append(f"  {BOLD}Planning: {rel_path}{marker}{RESET}\n")

        all_tasks = timed_tasks + untimed_tasks

        if timed_tasks:
            first_slot = 0

            now_slot = None
            if date and date == datetime.date.today():
                now_m    = datetime.datetime.now().hour * 60 + datetime.datetime.now().minute
                now_slot = get_time_slot(now_m, step_size_hours)

            hours_line, scale_line = scale_lines(step_size_hours, first_slot, now_slot)
            lines.append('  ' + hours_line)
            lines.append('  ' + scale_line)

            for i, task in enumerate(timed_tasks):
                lines.append(PlannerTool._task_row(task, step_size_hours, first_slot, cursor_idx == i))
                lines.extend(subtask_rows(task, left_pad=PlannerTool._icon_col(task, step_size_hours, first_slot)))
        else:
            lines.append(f"  {GRAY}No timed tasks yet{RESET}")

        if untimed_tasks:
            lines.append(f"\n  {GRAY}── Unscheduled {'─' * 50}{RESET}")
            for j, task in enumerate(untimed_tasks):
                lines.append(PlannerTool._task_row(task, step_size_hours, 0, cursor_idx == len(timed_tasks) + j))
                lines.extend(subtask_rows(task, left_pad=PlannerTool._icon_col(task, step_size_hours, 0)))

        if not all_tasks:
            lines.append(f"\n  {GRAY}No tasks. Press n to add one.{RESET}")

        lines.append(f"\n  {GRAY}[j/k] move  [h/l] shift  [H/L] end time  [r] remove time  [n] new  [q] quit{RESET}")

        cols = shutil.get_terminal_size(fallback=(80, 24)).columns
        padded = [ansi_truncate_pad(line, cols) for line in '\n'.join(lines).split('\n')]
        sys.stdout.write('\x1b[?25l\x1b[H' + '\n'.join(padded) + '\x1b[J\x1b[?25h')
        sys.stdout.flush()

    # ── Week planner ──────────────────────────────────────────────────────────

    DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

    @staticmethod
    def run_week(directory='.'):
        today = datetime.date.today()
        monday = today - datetime.timedelta(days=today.weekday())
        week_days = [monday + datetime.timedelta(days=i) for i in range(7)]

        file_paths = []
        week_tasks = []
        all_tasks_per_day = []
        for day in week_days:
            files = FileFinder.find_journal_files(directory, date_from=day, date_to=day)
            if files:
                all_tasks = TaskParser.parse_file(files[0])
                file_paths.append(files[0])
                all_tasks_per_day.append(all_tasks)
                week_tasks.append([t for t in all_tasks if t.parent is None])
            else:
                file_paths.append(None)
                all_tasks_per_day.append([])
                week_tasks.append([])

        PlannerTool.interactive_week(week_days, week_tasks, file_paths, all_tasks_per_day, directory)

    @staticmethod
    def _week_cell(title: str, col_width: int, is_selected: bool) -> str:
        prefix = '> ' if is_selected else '  '
        text = prefix + title
        if len(text) > col_width:
            text = text[:col_width - 3] + '...'
        else:
            text = text.ljust(col_width)
        return f'\x1b[7m{text}{RESET}' if is_selected else text

    @staticmethod
    def render_week(week_days: list, week_tasks: list, cursor_col: int, cursor_row: int):
        cols = shutil.get_terminal_size(fallback=(80, 24)).columns
        col_width = max((cols - 2) // 7, 10)
        margin = '  '
        today = datetime.date.today()

        lines = []
        monday, sunday = week_days[0], week_days[-1]
        lines.append(f"{margin}{BOLD}Week {monday.strftime('%b %d')} – {sunday.strftime('%b %d, %Y')}{RESET}\n")

        # Day headers
        header = margin
        for i, day in enumerate(week_days):
            label = f"{PlannerTool.DAY_NAMES[i]} {day.strftime('%m/%d')}"
            padded = label.ljust(col_width)
            header += f"{BOLD}{padded}{RESET}" if day == today else padded
        lines.append(header)
        lines.append(margin + ('─' * (col_width - 1) + ' ') * 7)

        # Task rows — at least 1 row so the cursor is always visible
        max_rows = max(max((len(t) for t in week_tasks), default=0), 1)
        for row in range(max_rows):
            line = margin
            for col_idx in range(7):
                tasks = week_tasks[col_idx]
                is_selected = (col_idx == cursor_col and row == cursor_row)
                if row < len(tasks):
                    line += PlannerTool._week_cell(tasks[row].title, col_width, is_selected)
                elif is_selected:
                    line += PlannerTool._week_cell('', col_width, True)
                else:
                    line += ' ' * col_width
            lines.append(line)

        lines.append(f"\n{margin}{GRAY}[h/j/k/l] navigate  [H/L] move task left/right  [q] quit{RESET}")

        padded = [ansi_truncate_pad(line, cols) for line in '\n'.join(lines).split('\n')]
        sys.stdout.write('\x1b[?25l\x1b[H' + '\n'.join(padded) + '\x1b[J\x1b[?25h')
        sys.stdout.flush()

    @staticmethod
    def _move_task_week(week_tasks, src_col, dst_col, cursor_row) -> int:
        if not week_tasks[src_col] or not (0 <= cursor_row < len(week_tasks[src_col])):
            return cursor_row
        task = week_tasks[src_col].pop(cursor_row)
        week_tasks[dst_col].append(task)
        return len(week_tasks[dst_col]) - 1

    @staticmethod
    def _save_week(week_tasks, original_tasks_by_col, file_paths, all_tasks_per_day, week_days, directory):
        backed_up = set()
        dst_paths_written = set()
        for src_col in range(7):
            src_path = file_paths[src_col]
            if not src_path:
                continue
            current_ids = {id(t) for t in week_tasks[src_col]}
            departed = [
                (t, next((c for c, col in enumerate(week_tasks) if t in col), None))
                for t in original_tasks_by_col[src_col]
                if id(t) not in current_ids
            ]
            departed = [(t, dst) for t, dst in departed if dst is not None]
            if not departed:
                continue
            if src_path not in backed_up:
                BackupManager.backup(src_path, directory)
                backed_up.add(src_path)
            # Reverse line order: cutting from the bottom leaves earlier line numbers intact,
            # so each subsequent cut uses the original line numbers without re-parsing.
            departed.sort(key=lambda x: x[0].line_number, reverse=True)
            for task, dst_col in departed:
                if file_paths[dst_col] is None:
                    new_path = os.path.join(directory, week_days[dst_col].strftime('%Y-%m-%d.md'))
                    open(new_path, 'w').close()
                    file_paths[dst_col] = new_path
                dst_path = file_paths[dst_col]
                if dst_path not in backed_up:
                    BackupManager.backup(dst_path, directory)
                    backed_up.add(dst_path)
                block = FileWriter.cut_task(src_path, task, all_tasks_per_day[src_col])
                FileWriter.paste_task(dst_path, block)
                dst_paths_written.add(dst_path)

        for path in dst_paths_written:
            all_tasks = TaskParser.parse_file(path)
            timed = [t for t in all_tasks if t.time is not None and t.parent is None]
            FileWriter.sort_timed_tasks(path, timed, all_tasks)

    @staticmethod
    def interactive_week(
        week_days: list, week_tasks: list,
        file_paths: list, all_tasks_per_day: list, directory: str,
    ):
        cursor_col = next((i for i, t in enumerate(week_tasks) if t), 0)
        cursor_row = 0
        has_changes = False
        original_tasks_by_col = [list(col) for col in week_tasks]

        while True:
            PlannerTool.render_week(week_days, week_tasks, cursor_col, cursor_row)
            key = PlannerTool.read_key()

            if key in ('q', '\x03'):
                if has_changes:
                    sys.stdout.write('\x1b[2J\x1b[H')
                    sys.stdout.flush()
                    confirm = input("Save changes? [y/n]: ").strip().lower()
                    if confirm == 'y':
                        PlannerTool._save_week(
                            week_tasks, original_tasks_by_col,
                            file_paths, all_tasks_per_day, week_days, directory,
                        )
                        print("✓ Changes saved")
                break

            elif key == 'j':
                tasks = week_tasks[cursor_col]
                if tasks:
                    cursor_row = min(cursor_row + 1, len(tasks) - 1)

            elif key == 'k':
                cursor_row = max(cursor_row - 1, 0)

            elif key == 'h':
                new_col = max(cursor_col - 1, 0)
                cursor_col = new_col
                cursor_row = min(cursor_row, max(len(week_tasks[new_col]) - 1, 0))

            elif key == 'l':
                new_col = min(cursor_col + 1, 6)
                cursor_col = new_col
                cursor_row = min(cursor_row, max(len(week_tasks[new_col]) - 1, 0))

            elif key == 'H' and cursor_col > 0 and week_tasks[cursor_col]:
                cursor_row = PlannerTool._move_task_week(week_tasks, cursor_col, cursor_col - 1, cursor_row)
                cursor_col -= 1
                has_changes = True

            elif key == 'L' and cursor_col < 6 and week_tasks[cursor_col]:
                cursor_row = PlannerTool._move_task_week(week_tasks, cursor_col, cursor_col + 1, cursor_row)
                cursor_col += 1
                has_changes = True

    # ── Persistence ───────────────────────────────────────────────────────────

    @staticmethod
    def _has_changes(timed_tasks, untimed_tasks, original_lines, new_tasks) -> bool:
        if new_tasks:
            return True
        for task in timed_tasks + untimed_tasks:
            if task.line_number > 0 and task.line_number in original_lines:
                if original_lines[task.line_number] != task.to_line():
                    return True
        return False

    @staticmethod
    def _save(file_path, directory, timed_tasks, untimed_tasks, original_lines, new_tasks):
        BackupManager.backup(file_path, directory)

        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        for task in timed_tasks + untimed_tasks:
            if task.line_number in original_lines and original_lines[task.line_number] != task.to_line():
                lines[task.line_number - 1] = task.to_line() + '\n'

        for task in new_tasks:
            lines.append(task.to_line() + '\n')

        tmp = file_path + '.tmp'
        try:
            with open(tmp, 'w', encoding='utf-8') as f:
                f.writelines(lines)
            os.replace(tmp, file_path)
        except Exception:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise

        all_tasks = TaskParser.parse_file(file_path)
        timed = [t for t in all_tasks if t.time is not None and t.parent is None]
        FileWriter.sort_timed_tasks(file_path, timed, all_tasks)

    # ── Main loop ─────────────────────────────────────────────────────────────

    @staticmethod
    def interactive_plan(directory, file_path, tasks, date=None):
        step  = PlannerTool.STEP_SIZE_HOURS
        step_m = int(step * 60)

        timed_tasks   = sorted([t for t in tasks if t.time and t.parent is None],
                               key=lambda t: get_minutes(t.time.start))
        untimed_tasks = [t for t in tasks if not t.time and t.parent is None]
        new_tasks     = []

        original_lines = {t.line_number: t.to_line() for t in tasks if t.line_number > 0}
        cursor_idx = 0

        while True:
            all_tasks   = timed_tasks + untimed_tasks
            has_changes = PlannerTool._has_changes(timed_tasks, untimed_tasks, original_lines, new_tasks)
            PlannerTool.render(file_path, timed_tasks, untimed_tasks, cursor_idx,
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
                if all_tasks:
                    cursor_idx = min(cursor_idx + 1, len(all_tasks) - 1)

            elif key == 'k':
                cursor_idx = max(cursor_idx - 1, 0)

            elif key in ('h', 'l'):
                if not all_tasks:
                    continue
                task = all_tasks[cursor_idx]
                direction = -1 if key == 'h' else 1

                if task.time is None:
                    task.time = TaskTime(start='12:00')
                    untimed_tasks.remove(task)
                    timed_tasks.append(task)
                    timed_tasks.sort(key=lambda t: get_minutes(t.time.start))
                    cursor_idx = timed_tasks.index(task)
                else:
                    start_m = get_minutes(task.time.start)
                    if task.time.end:
                        end_m    = get_minutes(task.time.end)
                        duration = end_m - start_m
                        new_start = max(0, min(start_m + direction * step_m, 24 * 60 - duration))
                        task.time = TaskTime(
                            start=minutes_to_time(new_start),
                            end=minutes_to_time(new_start + duration),
                        )
                    else:
                        new_start = max(0, min(start_m + direction * step_m, 23 * 60 + 30))
                        task.time = TaskTime(start=minutes_to_time(new_start))
                    timed_tasks.sort(key=lambda t: get_minutes(t.time.start))
                    cursor_idx = timed_tasks.index(task)

            elif key == 'H':  # shrink: move end time earlier
                if not all_tasks:
                    continue
                task = all_tasks[cursor_idx]
                if task.time and task.time.end:
                    start_m = get_minutes(task.time.start)
                    end_m   = get_minutes(task.time.end)
                    new_end = end_m - step_m
                    if new_end > start_m:
                        task.time = TaskTime(start=task.time.start,
                                             end=minutes_to_time(new_end))
                    else:
                        task.time = TaskTime(start=task.time.start)

            elif key == 'L':  # extend: move end time later
                if not all_tasks:
                    continue
                task = all_tasks[cursor_idx]
                if task.time:
                    if task.time.end:
                        end_m   = get_minutes(task.time.end)
                        new_end = min(end_m + step_m, 24 * 60)
                    else:
                        start_m = get_minutes(task.time.start)
                        new_end = min(start_m + step_m, 24 * 60)
                    task.time = TaskTime(start=task.time.start,
                                         end=minutes_to_time(new_end))

            elif key == 'r':
                if all_tasks:
                    task = all_tasks[cursor_idx]
                    if task.time and task in timed_tasks:
                        task.time = None
                        timed_tasks.remove(task)
                        untimed_tasks.insert(0, task)
                        cursor_idx = min(cursor_idx, len(timed_tasks + untimed_tasks) - 1)

            elif key == 'n':
                sys.stdout.write('\x1b[2J\x1b[H')
                sys.stdout.flush()
                title = input("New task title: ").strip()
                if title:
                    new_task = Task(title=title, status='todo', time=None, line_number=-1, indent='')
                    untimed_tasks.append(new_task)
                    new_tasks.append(new_task)
                    cursor_idx = len(timed_tasks) + len(untimed_tasks) - 1
