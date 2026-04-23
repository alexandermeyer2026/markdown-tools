import datetime
import os
import re
import shutil
import sys
import termios
import tty

from models import Task, TaskTime
from os_utils import BackupManager, FileFinder
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
            print("Usage: journal planner <today|yesterday|tomorrow|YYYY-MM-DD|file>")
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
            if task.line_number > 0 and original_lines.get(task.line_number) != task.to_line():
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
