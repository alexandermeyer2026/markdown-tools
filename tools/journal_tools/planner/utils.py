import sys
import termios
import tty

from models import Task
from tools.journal_tools.rendering import get_minutes


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


def flatten_tasks(tasks: list) -> list:
    result = []
    for task in tasks:
        result.append(task)
        result.extend(flatten_tasks(task.children))
    return result


def task_to_lines(task: Task) -> list[str]:
    lines = [task.to_line() + '\n']
    for child in task.children:
        lines.extend(task_to_lines(child))
    return lines


def root_task(task: Task) -> Task:
    while task.parent is not None:
        task = task.parent
    return task


def week_expanded(tasks: list) -> list[Task]:
    """Flatten top-level tasks and all their descendants for week display, timed first."""
    timed = sorted([t for t in tasks if t.time], key=lambda t: get_minutes(t.time.start))
    untimed = [t for t in tasks if not t.time]
    result = []
    for task in timed + untimed:
        result.append(task)
        result.extend(flatten_tasks(task.children))
    return result
