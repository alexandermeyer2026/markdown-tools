from config import get_indent_step
from models import Task, get_minutes


def fix_parent_refs(tasks: list[Task], parent: Task | None) -> None:
    """Set parent refs and (for new tasks) correct indentation throughout a subtree."""
    parent_indent = parent.indent if parent else ""
    for task in tasks:
        task.parent = parent
        if task.line_number == -1:
            task.indent = parent_indent + get_indent_step()
        fix_parent_refs(task.children, task)


def flatten_tasks(tasks: list) -> list:
    result = []
    for task in tasks:
        result.append(task)
        result.extend(flatten_tasks(task.children))
    return result


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
