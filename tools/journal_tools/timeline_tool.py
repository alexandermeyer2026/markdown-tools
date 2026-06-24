import datetime
import os
import shutil

from models import Task
from os_utils import FileFinder, resolve_date
from models.file import TaskBlock, parse
from models import get_minutes
from tools.journal_tools.rendering import (
    STATUS_ICONS, STATUS_COLORS, GRAY, WHITE, RESET,
    get_time_slot, scale_lines, body_rows, subtask_rows,
    insert_now_marker,
)

_STEP_SIZES = [0.25, 0.5, 1]


class TimelineTool:

    @staticmethod
    def run(args, directory='.'):
        if not args:
            print("Usage: main.py journal timeline <today|yesterday|tomorrow|YYYY-MM-DD|file>")
            return
        input_file = args[0]
        basename = os.path.basename(input_file)

        date = resolve_date(basename) or FileFinder.get_journal_file_date(input_file)

        if date:
            directory = os.path.dirname(input_file) or directory
            if journal_files := FileFinder.find_journal_files(
                directory,
                date_from=date,
                date_to=date
            ):
                input_file = journal_files[0]
            else:
                print(f"No journal files for {date} found")
                return
        else:
            if not os.path.exists(input_file):
                print(f"File {input_file} does not exist")
                return

        nodes = parse(input_file)
        top_level_blocks = [n for n in nodes if isinstance(n, TaskBlock)]
        TimelineTool.render_timeline(top_level_blocks, date=date)

    @staticmethod
    def render_scale(step_size_hours: float, first_task_slot: int, now_marker_slot: int) -> None:
        hours_line, scale_line = scale_lines(step_size_hours, first_task_slot, now_marker_slot)
        print(hours_line)
        print(scale_line)

    @staticmethod
    def _step_size_for_width(first_task_minutes: int, width: int) -> float:
        for step in _STEP_SIZES:
            first_slot = get_time_slot(first_task_minutes, step)
            if int(24 / step) - first_slot <= width:
                return step
        return _STEP_SIZES[-1]

    @staticmethod
    def render_task(task: Task, step_size_hours: float, first_task_slot: int, now_marker_slot: int) -> str:
        start_minutes = get_minutes(task.time.start)
        start_slot = end_slot = get_time_slot(start_minutes, step_size_hours)
        if task.time.end:
            end_minutes = get_minutes(task.time.end)
            end_slot = get_time_slot(end_minutes - 1, step_size_hours)

        line = ' ' * start_slot
        bar = '█' * max(end_slot - start_slot + 1, 1)

        if (now_marker_slot is not None and start_slot <= now_marker_slot <= end_slot) and task.status == 'todo':
            line += bar
        elif task.status not in STATUS_COLORS:
            line += GRAY + bar + RESET
        else:
            line += STATUS_COLORS[task.status] + bar + RESET

        line += ' ' + STATUS_ICONS.get(task.status, '?')
        line += ' ' + task.time.to_str()
        line += ' \033[1m' + task.title + '\033[0m'
        line = line[first_task_slot:]

        return line

    @staticmethod
    def _icon_col(task: Task, step_size_hours: float, first_task_slot: int) -> int:
        start_slot = get_time_slot(get_minutes(task.time.start), step_size_hours)
        end_slot = start_slot
        if task.time.end:
            end_slot = get_time_slot(get_minutes(task.time.end) - 1, step_size_hours)
        bar_width = max(end_slot - start_slot + 1, 1)
        return (start_slot - first_task_slot) + bar_width + 1

    @staticmethod
    def render_timeline_lines(blocks: list, date: datetime.date, width: int) -> list[str]:
        timed_blocks = [b for b in blocks if b.task.time and b.task.time.start]
        timed_blocks.sort(key=lambda b: get_minutes(b.task.time.start))

        if not timed_blocks:
            return ["No timed tasks found"]

        first_task_minutes = get_minutes(timed_blocks[0].task.time.start)
        step = TimelineTool._step_size_for_width(first_task_minutes, width)
        first_task_slot = get_time_slot(first_task_minutes, step)

        now_marker_slot = None
        if date == datetime.date.today():
            now = datetime.datetime.now()
            now_marker_slot = get_time_slot(now.hour * 60 + now.minute, step)

        hours_line, scale_line = scale_lines(step, first_task_slot, now_marker_slot)

        now_col = None
        if now_marker_slot is not None:
            _col = now_marker_slot - first_task_slot
            if _col >= 0:
                now_col = _col
                hours_line = insert_now_marker(hours_line, now_col)
                scale_line = scale_line[:now_col] + WHITE + '▼' + RESET + scale_line[now_col + 1:]

        lines = [hours_line, scale_line]
        for block in timed_blocks:
            task = block.task
            icon_col = TimelineTool._icon_col(task, step, first_task_slot)
            task_line = TimelineTool.render_task(task, step, first_task_slot, now_marker_slot)
            task_body = body_rows(block, left_pad=icon_col)
            task_subtasks = subtask_rows(block, left_pad=icon_col)
            if now_col is not None:
                task_line = insert_now_marker(task_line, now_col)
                task_body = [insert_now_marker(l, now_col) for l in task_body]
                task_subtasks = [insert_now_marker(l, now_col) for l in task_subtasks]
            lines.append(task_line)
            lines.extend(task_body)
            lines.extend(task_subtasks)

        return lines

    @staticmethod
    def render_timeline(blocks: list, date: datetime.date) -> None:
        try:
            width = shutil.get_terminal_size().columns
        except (OSError, AttributeError):
            width = 80
        for line in TimelineTool.render_timeline_lines(blocks, date, width):
            print(line)
