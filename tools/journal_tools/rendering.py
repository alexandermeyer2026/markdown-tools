import math
import re
import textwrap

from models import Task, get_minutes, minutes_to_time
from models.file import RawLine, TaskBlock

STATUS_ICONS: dict[str, str] = {
    'todo':        '○',
    'in progress': '◐',
    'done':        '✓',
    'failed':      '✗',
    'started':     '~',
}

# Rich styles — used by the Textual planner screens
STATUS_STYLES: dict[str, str] = {
    'todo':        'bright_black',
    'in progress': 'blue',
    'done':        'green',
    'failed':      'red',
    'started':     'yellow',
}

# ANSI constants — used by non-Textual tools (catch_up, timeline, update)
STATUS_COLORS: dict[str, str] = {
    'todo':        '\x1b[90m',
    'in progress': '\x1b[34m',
    'done':        '\x1b[32m',
    'failed':      '\x1b[31m',
    'started':     '\x1b[33m',
}
BOLD   = '\x1b[1m'
ITALIC = '\x1b[3m'
GRAY   = '\x1b[90m'
WHITE  = '\x1b[97m'
RED    = '\x1b[31m'
GREEN  = '\x1b[32m'
RESET  = '\x1b[0m'

_ANSI_RE = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]')


def get_time_slot(minutes: int, step_size_hours: float) -> int:
    return math.floor(minutes / 60 / step_size_hours)


def scale_lines(step_size_hours: float, first_slot: int, now_slot: int | None) -> tuple[str, str]:
    """Return (hours_line, scale_line) as plain Unicode strings (no ANSI)."""
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


def insert_now_marker(line: str, col: int) -> str:
    """Insert a gray │ at col — only in the leading blank margin or after the content ends."""
    # First pass: find content_start (first non-space visible col) and total visible length.
    content_start = None
    visible = 0
    i = 0
    while i < len(line):
        m = _ANSI_RE.match(line, i)
        if m:
            i = m.end()
        else:
            if line[i] != ' ' and content_start is None:
                content_start = visible
            visible += 1
            i += 1
    if content_start is None:
        content_start = visible  # line is all spaces

    if col >= content_start and col < visible:
        return line  # col lands inside content — skip

    if col >= visible:
        return line + ' ' * (col - visible) + GRAY + '│' + RESET

    # col is in leading blank margin — replace the space
    out = []
    vis = 0
    i = 0
    while i < len(line):
        m = _ANSI_RE.match(line, i)
        if m:
            out.append(m.group())
            i = m.end()
        else:
            out.append(GRAY + '│' + RESET if vis == col else line[i])
            vis += 1
            i += 1
    return ''.join(out)


def body_rows(block: TaskBlock, left_pad: int = 0, depth: int = 0) -> list[str]:
    body_lines = [n.raw.rstrip('\n') for n in block.nodes if isinstance(n, RawLine) and n is not block.tag_node]
    if not body_lines:
        return []
    body_text = textwrap.dedent('\n'.join(body_lines)).strip()
    if not body_text:
        return []
    prefix = ' ' * left_pad + '  ' * (depth + 1)
    rows = []
    for line in body_text.split('\n'):
        stripped = line.strip()
        if stripped:
            rows.append(f"{prefix}{GRAY}{ITALIC}{stripped}{RESET}")
    return rows


def subtask_rows(block: TaskBlock, left_pad: int = 0, depth: int = 1, selected_task=None) -> list[str]:
    rows = []
    for child_block in [n for n in block.nodes if isinstance(n, TaskBlock)]:
        child = child_block.task
        indent = ' ' * left_pad + '  ' * depth
        icon = STATUS_ICONS.get(child.status, '?')
        if child is selected_task:
            rows.append(f"{indent[:-2]}\x1b[7m> {icon} {child.title}{RESET}")
        else:
            status_color = STATUS_COLORS.get(child.status, GRAY)
            rows.append(f"{indent}{status_color}{icon}{RESET} {child.title}")
        rows.extend(body_rows(child_block, left_pad, depth))
        rows.extend(subtask_rows(child_block, left_pad, depth + 1, selected_task))
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


def ansi_truncate(line: str, cols: int) -> str:
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
            out.append(RESET)
            break
    return ''.join(out)
