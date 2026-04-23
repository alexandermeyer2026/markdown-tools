import calendar
import datetime
import os
import shutil

from os_utils import FileFinder
from parser import TaskParser
from tools.journal_tools.rendering import (
    STATUS_ICONS, STATUS_COLORS, BOLD, GRAY, RESET,
    get_minutes, get_time_slot, scale_lines,
)

RED   = '\x1b[31m'
CYAN  = '\x1b[36m'


class UpdateTool:

    OVERDUE_DAYS  = 14
    UPCOMING_DAYS = 7

    @staticmethod
    def run(args, directory='.'):
        today = datetime.date.today()
        now   = datetime.datetime.now()

        overdue_by_date  = UpdateTool._gather(directory,
                               today - datetime.timedelta(days=UpdateTool.OVERDUE_DAYS),
                               today - datetime.timedelta(days=1))
        today_tasks      = UpdateTool._tasks_for_date(directory, today)
        upcoming_by_date = UpdateTool._gather(directory,
                               today + datetime.timedelta(days=1),
                               today + datetime.timedelta(days=UpdateTool.UPCOMING_DAYS))

        overdue = [
            (d, t)
            for d, tasks in sorted(overdue_by_date.items())
            for t in tasks
            if t.status in ('todo', 'in progress', 'started') and t.parent is None
        ]
        upcoming = {
            d: [t for t in tasks if t.parent is None]
            for d, tasks in sorted(upcoming_by_date.items())
            if any(t.parent is None for t in tasks)
        }

        blocks = []
        blocks.append(UpdateTool._header(today, now))
        blocks.append(UpdateTool._calendar(today))
        if overdue:
            blocks.append(UpdateTool._section_overdue(overdue))
        blocks.append(UpdateTool._section_today(today, now, today_tasks))
        if upcoming:
            blocks.append(UpdateTool._section_upcoming(today, upcoming))

        print('\n\n'.join('\n'.join(b) for b in blocks))

    # ── Data helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _gather(directory, date_from, date_to):
        files = FileFinder.find_journal_files(directory, date_from=date_from, date_to=date_to)
        result = {}
        for f in files:
            date = FileFinder.get_journal_file_date(f)
            result[date] = TaskParser.parse_file(f)
        return result

    @staticmethod
    def _tasks_for_date(directory, date):
        files = FileFinder.find_journal_files(directory, date_from=date, date_to=date)
        return TaskParser.parse_file(files[0]) if files else []

    # ── Rendering helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _cols():
        return shutil.get_terminal_size(fallback=(80, 24)).columns

    @staticmethod
    def _divider(label):
        cols = UpdateTool._cols()
        bar_len = max(0, cols - len(label) - 7)
        return f"  {GRAY}──{RESET} {BOLD}{label}{RESET} {GRAY}{'─' * bar_len}{RESET}"

    # ── Header ────────────────────────────────────────────────────────────────

    @staticmethod
    def _header(today, now):
        day_name  = today.strftime('%A')
        date_str  = today.strftime('%-d %B %Y')
        week_num  = today.isocalendar()[1]
        time_str  = now.strftime('%H:%M')

        left_text  = f"  {day_name}, {date_str}  ·  Week {week_num}"
        right_text = f"{time_str}  "
        gap = max(1, UpdateTool._cols() - len(left_text) - len(right_text))

        left  = f"  {BOLD}{day_name}, {date_str}{RESET}  {GRAY}·  Week {week_num}{RESET}"
        right = f"{BOLD}{time_str}{RESET}  "
        return [left + ' ' * gap + right]

    # ── Calendar ──────────────────────────────────────────────────────────────

    @staticmethod
    def _calendar(today):
        month_name   = today.strftime('%B %Y')
        weeks        = calendar.monthcalendar(today.year, today.month)
        current_week = next(
            (i for i, w in enumerate(weeks) if today.day in w), None
        )

        lines = [f"  {BOLD}{month_name:^27}{RESET}"]
        lines.append(f"  {GRAY}Mo  Tu  We  Th  Fr  Sa  Su{RESET}")

        for week_idx, week in enumerate(weeks):
            row = '  '
            for day in week:
                if day == 0:
                    row += '    '
                elif day == today.day:
                    row += f"{BOLD}\x1b[7m{day:2d}{RESET}  "
                elif week_idx == current_week:
                    row += f"{day:2d}  "
                else:
                    row += f"{GRAY}{day:2d}{RESET}  "
            lines.append(row)

        return lines

    # ── Overdue ───────────────────────────────────────────────────────────────

    @staticmethod
    def _section_overdue(overdue):
        label = f"{'1 overdue task' if len(overdue) == 1 else f'{len(overdue)} overdue tasks'}"
        lines = [UpdateTool._divider(label)]
        for date, task in overdue:
            icon  = STATUS_ICONS.get(task.status, '○')
            date_label = date.strftime('%a %-d %b')
            lines.append(f"  {RED}{icon}{RESET}  {GRAY}{date_label:<11}{RESET}  {task.title}")
        return lines

    # ── Today ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _section_today(today, now, all_tasks):
        timed   = sorted(
            [t for t in all_tasks if t.time and t.parent is None],
            key=lambda t: get_minutes(t.time.start),
        )
        untimed = [t for t in all_tasks if not t.time and t.parent is None]

        total = len(timed) + len(untimed)
        done  = sum(1 for t in timed + untimed if t.status == 'done')

        now_m     = now.hour * 60 + now.minute
        next_task = next(
            (t for t in timed if get_minutes(t.time.start) > now_m and t.status != 'done'),
            None,
        )

        summary_parts = [f"{total} task{'s' if total != 1 else ''}"]
        if total:
            summary_parts.append(f"{done} ✓")
        if next_task:
            delta = get_minutes(next_task.time.start) - now_m
            h, m  = divmod(delta, 60)
            eta   = f"{h}h {m}m" if h else f"{m}m"
            summary_parts.append(f"next in {eta}")

        lines = [UpdateTool._divider('Today  ·  ' + '  ·  '.join(summary_parts))]

        if not timed and not untimed:
            lines.append(f"  {GRAY}No tasks today{RESET}")
            return lines

        if timed:
            step       = 0.5
            first_slot = get_time_slot(get_minutes(timed[0].time.start), step)
            now_slot   = get_time_slot(now_m, step)
            hours_line, scale_line = scale_lines(step, first_slot, now_slot)
            lines.append('  ' + hours_line)
            lines.append('  ' + scale_line)
            for task in timed:
                lines.append('  ' + UpdateTool._task_bar(task, step, first_slot))

        if untimed:
            if timed:
                lines.append('')
            for task in untimed:
                icon  = STATUS_ICONS.get(task.status, '○')
                color = STATUS_COLORS.get(task.status, GRAY)
                lines.append(f"  {color}{icon}{RESET}  {task.title}")

        return lines

    @staticmethod
    def _task_bar(task, step, first_slot):
        color      = STATUS_COLORS.get(task.status, GRAY)
        icon       = STATUS_ICONS.get(task.status, '○')
        start_m    = get_minutes(task.time.start)
        start_slot = get_time_slot(start_m, step)
        end_slot   = start_slot
        if task.time.end:
            end_slot = get_time_slot(get_minutes(task.time.end) - 1, step)
        bar    = color + '█' * max(end_slot - start_slot + 1, 1) + RESET
        offset = start_slot - first_slot
        return ' ' * offset + bar + f"  {color}{icon}{RESET}  {task.time.to_str()}  {BOLD}{task.title}{RESET}"

    # ── Upcoming ──────────────────────────────────────────────────────────────

    @staticmethod
    def _section_upcoming(today, upcoming_by_date):
        lines = [UpdateTool._divider('Upcoming')]
        for date in sorted(upcoming_by_date):
            tasks = upcoming_by_date[date]
            delta = (date - today).days
            if delta == 1:
                label = f"Tomorrow, {date.strftime('%-d %b')}"
            else:
                label = date.strftime('%A, %-d %b')
            lines.append(f"  {BOLD}{label}{RESET}")
            for task in tasks:
                icon        = STATUS_ICONS.get(task.status, '○')
                color       = STATUS_COLORS.get(task.status, GRAY)
                time_prefix = f"{GRAY}{task.time.to_str()}  {RESET}" if task.time else ''
                lines.append(f"  {color}{icon}{RESET}  {time_prefix}{task.title}")
        return lines
