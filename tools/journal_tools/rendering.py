import math
import re

from models import Task

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

_ANSI_RE = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]')


def get_minutes(time_str: str) -> int:
    m = re.match(r'(\d{1,2}):(\d{2})', time_str)
    if not m:
        raise ValueError(f"Invalid time string: {time_str}")
    return int(m.group(1)) * 60 + int(m.group(2))


def minutes_to_time(minutes: int) -> str:
    if minutes >= 24 * 60:
        return '24:00'
    return f"{max(0, minutes) // 60}:{max(0, minutes) % 60:02d}"


def get_time_slot(minutes: int, step_size_hours: float) -> int:
    return math.floor(minutes / 60 / step_size_hours)


def scale_lines(step_size_hours: float, first_slot: int, now_slot: int | None) -> tuple[str, str]:
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


def subtask_rows(task: Task, left_pad: int = 0, depth: int = 1) -> list[str]:
    rows = []
    for child in task.children:
        indent = ' ' * left_pad + '  ' * depth
        icon = STATUS_ICONS.get(child.status, '?')
        rows.append(f"{indent}{GRAY}{icon} {child.title}{RESET}")
        rows.extend(subtask_rows(child, left_pad, depth + 1))
    return rows


def ansi_truncate_pad(line: str, cols: int) -> str:
    out, visible = [], 0
    i = 0
    while i < len(line):
        m = _ANSI_RE.match(line, i)
        if m:
            out.append(m.group())
            i = m.end()
        elif visible < cols:
            out.append(line[i])
            visible += 1
            i += 1
        else:
            break
    out.append(RESET + ' ' * (cols - visible))
    return ''.join(out)
