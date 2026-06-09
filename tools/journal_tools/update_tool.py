import calendar
import datetime
import os
import shutil

from os_utils import FileFinder
from parser import TaskParser
from tools.journal_tools.rendering import (
    STATUS_ICONS, STATUS_COLORS, BOLD, GRAY, RED, RESET,
    ansi_truncate_pad, body_rows, get_minutes,
)
from tools.journal_tools.timeline_tool import TimelineTool

CLOCK_DIGITS = {
    '0': ["███", "█ █", "█ █", "█ █", "███"],
    '1': [" █ ", " █ ", " █ ", " █ ", " █ "],
    '2': ["███", "  █", "███", "█  ", "███"],
    '3': ["███", "  █", "███", "  █", "███"],
    '4': ["█ █", "█ █", "███", "  █", "  █"],
    '5': ["███", "█  ", "███", "  █", "███"],
    '6': ["███", "█  ", "███", "█ █", "███"],
    '7': ["███", "  █", "  █", "  █", "  █"],
    '8': ["███", "█ █", "███", "█ █", "███"],
    '9': ["███", "█ █", "███", "  █", "███"],
    ':': ["   ", " █ ", "   ", " █ ", "   "],
}


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

        overdue = []
        for d, tasks in sorted(overdue_by_date.items()):
            day = [t for t in tasks if t.status in ('todo', 'in progress', 'started') and t.parent is None]
            timed   = sorted([t for t in day if t.time], key=lambda t: get_minutes(t.time.start))
            untimed = [t for t in day if not t.time]
            overdue.extend((d, t) for t in timed + untimed)
        upcoming = {
            d: [t for t in tasks if t.parent is None]
            for d, tasks in sorted(upcoming_by_date.items())
            if any(t.parent is None for t in tasks)
        }

        blocks = []
        blocks.append(UpdateTool._header_and_calendar(today, now))
        blocks.append(UpdateTool._three_columns(today, now, overdue, today_tasks, upcoming))

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
    def _col_divider(label, width):
        bar_len = max(0, width - len(label) - 5)
        return f"{GRAY}──{RESET} {BOLD}{label}{RESET} {GRAY}{'─' * bar_len}{RESET}"

    # ── Header + Calendar ─────────────────────────────────────────────────────

    # Visual width of one clock line: 2 indent + 5 glyphs × 3 + 4 separator spaces
    _CLOCK_VISUAL_W = 21

    @staticmethod
    def _big_clock_lines(now):
        time_str = now.strftime('%H:%M')
        lines = []
        for row in range(5):
            parts = [CLOCK_DIGITS.get(ch, ['   '] * 5)[row] for ch in time_str]
            lines.append('  ' + ' '.join(parts))
        return lines

    @staticmethod
    def _calendar_lines(today):
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

    @staticmethod
    def _header_and_calendar(today, now):
        cols = UpdateTool._cols()

        day_name = today.strftime('%A')
        date_str = today.strftime('%-d %B %Y')
        week_num = today.isocalendar()[1]

        header_vis = f"{day_name}, {date_str}  ·  Week {week_num}"
        header_pad = ' ' * max(0, (cols - len(header_vis)) // 2)
        header     = f"{header_pad}{BOLD}{day_name}, {date_str}{RESET}  {GRAY}·  Week {week_num}{RESET}"

        clock_lines = UpdateTool._big_clock_lines(now)
        cal_lines   = UpdateTool._calendar_lines(today)

        gap    = '   '
        n      = len(cal_lines)
        pad_r  = max(0, (n - 5) // 2)
        empty  = ' ' * UpdateTool._CLOCK_VISUAL_W

        clock_padded = [empty] * pad_r + clock_lines + [empty] * (n - pad_r - 5)

        block_w   = UpdateTool._CLOCK_VISUAL_W + len(gap) + 29  # clock + gap + calendar
        block_pad = ' ' * max(0, (cols - block_w) // 2)

        result = [header]
        for c, cal in zip(clock_padded, cal_lines):
            result.append(block_pad + c + gap + cal)
        return result

    # ── Three-column layout ───────────────────────────────────────────────────

    @staticmethod
    def _col_overdue(overdue, col_w):
        n     = len(overdue)
        label = f"Overdue{'  ·  ' + str(n) if n else ''}"
        pad   = lambda s: ansi_truncate_pad(s, col_w)
        lines = [pad(UpdateTool._col_divider(label, col_w))]
        if not overdue:
            lines.append(pad(f"  {GRAY}–{RESET}"))
        else:
            for date, task in overdue:
                icon = STATUS_ICONS.get(task.status, '○')
                lines.append(pad(
                    f"  {RED}{icon}{RESET}  {GRAY}{date.strftime('%a %-d %b')}{RESET}  {task.title}"
                ))
                for bline in body_rows(task, left_pad=2):
                    lines.append(pad(bline))
                lines.extend(UpdateTool._subtask_lines(task, pad))
        return lines

    @staticmethod
    def _col_today(today, now, all_tasks, col_w):
        timed   = sorted([t for t in all_tasks if t.time and t.parent is None],
                         key=lambda t: get_minutes(t.time.start))
        untimed = [t for t in all_tasks if not t.time and t.parent is None]
        total   = len(timed) + len(untimed)
        done    = sum(1 for t in timed + untimed if t.status == 'done')

        now_m     = now.hour * 60 + now.minute
        next_task = next(
            (t for t in timed if get_minutes(t.time.start) > now_m and t.status != 'done'), None
        )
        summary = [f"{total} task{'s' if total != 1 else ''}", f"{done} ✓"]
        if next_task:
            delta = get_minutes(next_task.time.start) - now_m
            h, m  = divmod(delta, 60)
            summary.append(f"next in {f'{h}h {m}m' if h else f'{m}m'}")

        pad   = lambda s: ansi_truncate_pad(s, col_w)
        lines = [pad(UpdateTool._col_divider('Today  ·  ' + '  ·  '.join(summary), col_w))]

        if not timed and not untimed:
            lines.append(pad(f"  {GRAY}No tasks today{RESET}"))
            return lines

        if timed:
            for line in TimelineTool.render_timeline_lines(timed, today, col_w - 2):
                lines.append(pad('  ' + line))

        if timed and untimed:
            lines.append(' ' * col_w)
        for task in untimed:
            icon  = STATUS_ICONS.get(task.status, '○')
            color = STATUS_COLORS.get(task.status, GRAY)
            lines.append(pad(f"  {color}{icon}{RESET}  {task.title}"))
            for bline in body_rows(task, left_pad=2):
                lines.append(pad(bline))
            lines.extend(UpdateTool._subtask_lines(task, pad))

        return lines

    @staticmethod
    def _subtask_lines(task, pad, depth=1):
        lines = []
        for child in task.children:
            cicon  = STATUS_ICONS.get(child.status, '○')
            indent = '  ' * (depth + 2)
            lines.append(pad(f"{indent}{GRAY}{cicon} {child.title}{RESET}"))
            for bline in body_rows(child, left_pad=0, depth=depth + 2):
                lines.append(pad(bline))
            lines.extend(UpdateTool._subtask_lines(child, pad, depth + 1))
        return lines

    @staticmethod
    def _col_upcoming(today, upcoming_by_date, col_w):
        pad   = lambda s: ansi_truncate_pad(s, col_w)
        lines = [pad(UpdateTool._col_divider('Upcoming', col_w))]
        if not upcoming_by_date:
            lines.append(pad(f"  {GRAY}–{RESET}"))
            return lines
        tomorrow = today + datetime.timedelta(days=1)
        for i, date in enumerate(sorted(upcoming_by_date)):
            tasks = upcoming_by_date[date]
            timed   = sorted([t for t in tasks if t.time], key=lambda t: get_minutes(t.time.start))
            untimed = [t for t in tasks if not t.time]
            delta = (date - today).days
            label = f"Tomorrow, {date.strftime('%-d %b')}" if delta == 1 else date.strftime('%A, %-d %b')
            if i > 0:
                lines.append(' ' * col_w)
            lines.append(pad(f"  {BOLD}{label}{RESET}"))
            if date == tomorrow and timed:
                for line in TimelineTool.render_timeline_lines(timed, date, col_w - 2):
                    lines.append(pad('  ' + line))
            else:
                for task in timed:
                    icon        = STATUS_ICONS.get(task.status, '○')
                    color       = STATUS_COLORS.get(task.status, GRAY)
                    time_prefix = f"{GRAY}{task.time.to_str()}  {RESET}"
                    lines.append(pad(f"  {color}{icon}{RESET}  {time_prefix}{task.title}"))
                    for bline in body_rows(task, left_pad=2):
                        lines.append(pad(bline))
                    lines.extend(UpdateTool._subtask_lines(task, pad))
            for task in untimed:
                icon  = STATUS_ICONS.get(task.status, '○')
                color = STATUS_COLORS.get(task.status, GRAY)
                lines.append(pad(f"  {color}{icon}{RESET}  {task.title}"))
                for bline in body_rows(task, left_pad=2):
                    lines.append(pad(bline))
                lines.extend(UpdateTool._subtask_lines(task, pad))
        return lines

    @staticmethod
    def _three_columns(today, now, overdue, today_tasks, upcoming_by_date):
        sep   = '  │  '
        col_w = max(10, (UpdateTool._cols() - len(sep) * 2) // 3)

        c1 = UpdateTool._col_overdue(overdue, col_w)
        c2 = UpdateTool._col_today(today, now, today_tasks, col_w)
        c3 = UpdateTool._col_upcoming(today, upcoming_by_date, col_w)

        height = max(len(c1), len(c2), len(c3))
        empty  = ' ' * col_w
        c1 += [empty] * (height - len(c1))
        c2 += [empty] * (height - len(c2))
        c3 += [empty] * (height - len(c3))

        return [a + sep + b + sep + c for a, b, c in zip(c1, c2, c3)]
