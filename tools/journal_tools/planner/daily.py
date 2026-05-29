import datetime
import os
import shutil
import sys

from models import Task
from os_utils import BackupManager, FileWriter
from parser import TaskParser
from tools.journal_tools.rendering import (
    STATUS_ICONS, STATUS_COLORS, BOLD, GRAY, RESET,
    get_minutes, get_time_slot, minutes_to_time,
    scale_lines, subtask_rows, ansi_truncate_pad,
)
from .utils import flatten_tasks


def task_row(task: Task, step_size_hours: float, first_slot: int, is_selected: bool) -> str:
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


def icon_col(task: Task, step_size_hours: float, first_slot: int) -> int:
    if not task.time:
        return 2
    start_m = get_minutes(task.time.start)
    start_slot = get_time_slot(start_m, step_size_hours)
    end_slot = start_slot
    if task.time.end:
        end_slot = get_time_slot(get_minutes(task.time.end) - 1, step_size_hours)
    bar_width = max(end_slot - start_slot + 1, 1)
    return 2 + (start_slot - first_slot) + bar_width + 1 + len(task.time.to_str()) + 1


def render(file_path, timed_tasks, untimed_tasks, selected_task,
           step_size_hours, directory, has_changes_flag, date):
    lines = []

    rel_path = os.path.relpath(file_path, directory)
    marker = ' *' if has_changes_flag else ''
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
            lines.append(task_row(task, step_size_hours, first_slot, task is selected_task))
            lines.extend(subtask_rows(task, left_pad=icon_col(task, step_size_hours, first_slot), selected_task=selected_task))
    else:
        lines.append(f"  {GRAY}No timed tasks yet{RESET}")

    if untimed_tasks:
        lines.append(f"\n  {GRAY}── Unscheduled {'─' * 50}{RESET}")
        for task in untimed_tasks:
            lines.append(task_row(task, step_size_hours, 0, task is selected_task))
            lines.extend(subtask_rows(task, left_pad=icon_col(task, step_size_hours, 0), selected_task=selected_task))

    if not timed_tasks and not untimed_tasks:
        lines.append(f"\n  {GRAY}No tasks. Press n to add one.{RESET}")

    lines.append(f"\n  {GRAY}[j/k] move  [h/l] shift  [H/L] end time  [r] remove time  [n] new  [t/i/d/f] status  [q] quit{RESET}")

    cols = shutil.get_terminal_size(fallback=(80, 24)).columns
    padded = [ansi_truncate_pad(line, cols) for line in '\n'.join(lines).split('\n')]
    sys.stdout.write('\x1b[?25l\x1b[H' + '\n'.join(padded) + '\x1b[J\x1b[?25h')
    sys.stdout.flush()


def has_changes(timed_tasks, untimed_tasks, original_lines, new_tasks) -> bool:
    if new_tasks:
        return True
    for task in flatten_tasks(timed_tasks + untimed_tasks):
        if task.line_number > 0 and task.line_number in original_lines:
            if original_lines[task.line_number] != task.to_line():
                return True
    return False


def save(file_path, directory, timed_tasks, untimed_tasks, original_lines, new_tasks):
    BackupManager.backup(file_path, directory)

    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    for task in flatten_tasks(timed_tasks + untimed_tasks):
        if task.line_number in original_lines and original_lines[task.line_number] != task.to_line():
            lines[task.line_number - 1] = task.to_line() + '\n'

    for task in new_tasks:
        if lines and lines[-1] != '\n':
            lines.append('\n')
        lines.append(task.to_line() + '\n')

    FileWriter.write_atomic(file_path, lines)

    all_tasks = TaskParser.parse_file(file_path)
    timed = [t for t in all_tasks if t.time is not None and t.parent is None]
    FileWriter.sort_timed_tasks(file_path, timed, all_tasks)
