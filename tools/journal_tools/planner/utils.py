from models import Task, get_minutes


def flatten_tasks(tasks: list) -> list:
    result = []
    for task in tasks:
        result.append(task)
        result.extend(flatten_tasks(task.children))
    return result


def task_body_lines(task: Task) -> list[str]:
    if not task.body:
        return []
    body_indent = (task.indent or '') + '    '
    result = []
    for line in task.body.split('\n'):
        stripped = line.strip()
        result.append(body_indent + stripped + '\n' if stripped else '\n')
    return result


def task_to_lines(task: Task) -> list[str]:
    lines = [task.to_line() + '\n']
    lines.extend(task_body_lines(task))
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
