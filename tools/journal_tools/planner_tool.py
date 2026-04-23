import datetime
import math
import os
import re
import shutil
import sys
import termios
import tty

from models import Task, TaskTime
from os_utils import BackupManager, FileFinder
from parser import TaskParser


class PlannerTool:
    STEP_SIZE_HOURS = 0.25  # 15-minute steps

    STATUS_ICONS = {'todo': '○', 'in progress': '◐', 'done': '✓', 'failed': '✗', 'started': '~'}
    STATUS_COLORS = {
        'todo':        '\x1b[90m',
        'in progress': '\x1b[34m',
        'done':        '\x1b[32m',
        'failed':      '\x1b[31m',
    }
    BOLD  = '\x1b[1m'
    GRAY  = '\x1b[90m'
    RESET = '\x1b[0m'

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

    @staticmethod
    def get_minutes(time_str: str) -> int:
        m = re.match(r'(\d{1,2}):(\d{2})', time_str)
        if not m:
            raise ValueError(f"Invalid time string: {time_str}")
        return int(m.group(1)) * 60 + int(m.group(2))

    @staticmethod
    def minutes_to_time(minutes: int) -> str:
        if minutes >= 24 * 60:
            return '24:00'
        return f"{max(0, minutes) // 60}:{max(0, minutes) % 60:02d}"

    @staticmethod
    def get_time_slot(minutes: int, step_size_hours: float) -> int:
        return math.floor(minutes / 60 / step_size_hours)

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
    def _scale_lines(step_size_hours: float, first_slot: int, now_slot: int | None) -> tuple[str, str]:
        timeline_width = int(24 / step_size_hours)
        marker_time_step = 6 * step_size_hours
        markers = [h for h in range(24) if h % marker_time_step == 0]
        marker_width = timeline_width // len(markers)

        hours, scale = '', ''
        for marker in markers:
            hours += str(marker).ljust(marker_width)
            scale += '┼' + '─' * (marker_width - 1)
        scale = '├' + scale[1:] + '┤'

        if now_slot is not None:
            scale = scale[:now_slot] + '▼' + scale[now_slot + 1:]

        return (hours + '24')[first_slot:], scale[first_slot:]

    @staticmethod
    def _task_row(task: Task, step_size_hours: float, first_slot: int, is_selected: bool) -> str:
        icon  = PlannerTool.STATUS_ICONS.get(task.status, '?')
        color = PlannerTool.STATUS_COLORS.get(task.status, PlannerTool.GRAY)

        if task.time:
            label = f" {color}{icon}{PlannerTool.RESET} {PlannerTool.BOLD}{task.title}{PlannerTool.RESET}"
            start_m = PlannerTool.get_minutes(task.time.start)
            start_slot = end_slot = PlannerTool.get_time_slot(start_m, step_size_hours)
            if task.time.end:
                end_m = PlannerTool.get_minutes(task.time.end)
                end_slot = PlannerTool.get_time_slot(end_m - 1, step_size_hours)
            bar = color + '█' * max(end_slot - start_slot + 1, 1) + PlannerTool.RESET
            offset = start_slot - first_slot
            if is_selected:
                pre = ' ' * max(offset - 2, 0) + f'\x1b[7m>\x1b[0m '
            else:
                pre = ' ' * offset
            return '  ' + pre + bar + f" {task.time.to_str()}" + label
        else:
            label = f" {color}{icon}{PlannerTool.RESET} {PlannerTool.BOLD}{task.title}{PlannerTool.RESET}"
            prefix = f'\x1b[7m>{PlannerTool.RESET} ' if is_selected else '  '
            return prefix + label.lstrip()

    @staticmethod
    def _icon_col(task: Task, step_size_hours: float, first_slot: int) -> int:
        if not task.time:
            return 2  # '  ' prefix
        start_m = PlannerTool.get_minutes(task.time.start)
        start_slot = PlannerTool.get_time_slot(start_m, step_size_hours)
        end_slot = start_slot
        if task.time.end:
            end_slot = PlannerTool.get_time_slot(PlannerTool.get_minutes(task.time.end) - 1, step_size_hours)
        bar_width = max(end_slot - start_slot + 1, 1)
        return 2 + (start_slot - first_slot) + bar_width + 1 + len(task.time.to_str()) + 1

    @staticmethod
    def _subtask_rows(task: Task, left_pad: int = 0, depth: int = 1) -> list[str]:
        rows = []
        for child in task.children:
            indent = ' ' * left_pad + '  ' * depth
            icon = PlannerTool.STATUS_ICONS.get(child.status, '?')
            rows.append(f"{indent}{PlannerTool.GRAY}{icon} {child.title}{PlannerTool.RESET}")
            rows.extend(PlannerTool._subtask_rows(child, left_pad, depth + 1))
        return rows

    @staticmethod
    def render(file_path, timed_tasks, untimed_tasks, cursor_idx,
               step_size_hours, directory, has_changes, date):
        lines = []

        rel_path = os.path.relpath(file_path, directory)
        marker = ' *' if has_changes else ''
        lines.append(f"  {PlannerTool.BOLD}Planning: {rel_path}{marker}{PlannerTool.RESET}\n")

        all_tasks = timed_tasks + untimed_tasks

        if timed_tasks:
            first_slot = 0

            now_slot = None
            if date and date == datetime.date.today():
                now_m    = datetime.datetime.now().hour * 60 + datetime.datetime.now().minute
                now_slot = PlannerTool.get_time_slot(now_m, step_size_hours)

            hours_line, scale_line = PlannerTool._scale_lines(step_size_hours, first_slot, now_slot)
            lines.append('  ' + hours_line)
            lines.append('  ' + scale_line)

            for i, task in enumerate(timed_tasks):
                lines.append(PlannerTool._task_row(task, step_size_hours, first_slot, cursor_idx == i))
                lines.extend(PlannerTool._subtask_rows(task, left_pad=PlannerTool._icon_col(task, step_size_hours, first_slot)))
        else:
            lines.append(f"  {PlannerTool.GRAY}No timed tasks yet{PlannerTool.RESET}")

        if untimed_tasks:
            lines.append(f"\n  {PlannerTool.GRAY}── Unscheduled {'─' * 50}{PlannerTool.RESET}")
            for j, task in enumerate(untimed_tasks):
                lines.append(PlannerTool._task_row(task, step_size_hours, 0, cursor_idx == len(timed_tasks) + j))
                lines.extend(PlannerTool._subtask_rows(task, left_pad=PlannerTool._icon_col(task, step_size_hours, 0)))

        if not all_tasks:
            lines.append(f"\n  {PlannerTool.GRAY}No tasks. Press n to add one.{PlannerTool.RESET}")

        lines.append(f"\n  {PlannerTool.GRAY}[j/k] move  [h/l] shift  [H/L] end time  [r] remove time  [n] new  [q] quit{PlannerTool.RESET}")

        cols = shutil.get_terminal_size(fallback=(80, 24)).columns
        ansi_re = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]')
        padded = []
        for line in '\n'.join(lines).split('\n'):
            out, visible = [], 0
            i = 0
            while i < len(line):
                m = ansi_re.match(line, i)
                if m:
                    out.append(m.group())
                    i = m.end()
                elif visible < cols:
                    out.append(line[i])
                    visible += 1
                    i += 1
                else:
                    break
            out.append(PlannerTool.RESET + ' ' * (cols - visible))
            padded.append(''.join(out))
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
                               key=lambda t: PlannerTool.get_minutes(t.time.start))
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
                    timed_tasks.sort(key=lambda t: PlannerTool.get_minutes(t.time.start))
                    cursor_idx = timed_tasks.index(task)
                else:
                    start_m = PlannerTool.get_minutes(task.time.start)
                    if task.time.end:
                        end_m    = PlannerTool.get_minutes(task.time.end)
                        duration = end_m - start_m
                        new_start = max(0, min(start_m + direction * step_m, 24 * 60 - duration))
                        task.time = TaskTime(
                            start=PlannerTool.minutes_to_time(new_start),
                            end=PlannerTool.minutes_to_time(new_start + duration),
                        )
                    else:
                        new_start = max(0, min(start_m + direction * step_m, 23 * 60 + 30))
                        task.time = TaskTime(start=PlannerTool.minutes_to_time(new_start))
                    timed_tasks.sort(key=lambda t: PlannerTool.get_minutes(t.time.start))
                    cursor_idx = timed_tasks.index(task)

            elif key == 'H':  # shrink: move end time earlier
                if not all_tasks:
                    continue
                task = all_tasks[cursor_idx]
                if task.time and task.time.end:
                    start_m = PlannerTool.get_minutes(task.time.start)
                    end_m   = PlannerTool.get_minutes(task.time.end)
                    new_end = end_m - step_m
                    if new_end > start_m:
                        task.time = TaskTime(start=task.time.start,
                                             end=PlannerTool.minutes_to_time(new_end))
                    else:
                        task.time = TaskTime(start=task.time.start)

            elif key == 'L':  # extend: move end time later
                if not all_tasks:
                    continue
                task = all_tasks[cursor_idx]
                if task.time:
                    if task.time.end:
                        end_m   = PlannerTool.get_minutes(task.time.end)
                        new_end = min(end_m + step_m, 24 * 60)
                    else:
                        start_m = PlannerTool.get_minutes(task.time.start)
                        new_end = min(start_m + step_m, 24 * 60)
                    task.time = TaskTime(start=task.time.start,
                                         end=PlannerTool.minutes_to_time(new_end))

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
