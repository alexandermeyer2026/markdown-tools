from models import Task, get_minutes


def flatten_tasks(tasks: list) -> list:
    result = []
    for task in tasks:
        result.append(task)
        result.extend(flatten_tasks(task.children))
    return result


def task_to_lines(task: Task) -> list[str]:
    lines = [task.to_line() + '\n']
    if task.body:
        body_indent = (task.indent or '') + '    '
        for line in task.body.split('\n'):
            stripped = line.strip()
            lines.append(body_indent + stripped + '\n' if stripped else '\n')
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
