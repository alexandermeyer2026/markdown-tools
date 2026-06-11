from config import get_indent_step
from models import Task, get_minutes


def fix_parent_refs(tasks: list[Task], parent: Task | None) -> None:
    """Set parent refs and (for new tasks) correct indentation throughout a subtree."""
    parent_indent = parent.indent if parent else ""
    for task in tasks:
        task.parent = parent
        if task.line_number == -1:
            task.indent = parent_indent + "  "
        fix_parent_refs(task.children, task)


def _block_lines(task: Task) -> set[int]:
    """All file line numbers that belong to this task's block."""
    lns: set[int] = set()
    if task.line_number > 0:
        lns.add(task.line_number)
        lns.update(task.body_line_numbers)
        for child in task.children:
            if child.line_number > 0:
                lns.update(_block_lines(child))
    return lns


def _has_new_descendants(task: Task) -> bool:
    return any(c.line_number == -1 for c in task.children) or any(
        _has_new_descendants(c) for c in task.children if c.line_number > 0
    )


def block_rewrite_tasks(flat_tasks: list[Task]) -> list[Task]:
    """Return outermost existing tasks that need a full block rewrite because new subtasks were added."""
    candidates = [t for t in flat_tasks if t.line_number > 0 and _has_new_descendants(t)]
    candidate_ids = {id(t) for t in candidates}

    def has_ancestor_in_set(task: Task) -> bool:
        p = task.parent
        while p is not None:
            if id(p) in candidate_ids:
                return True
            p = p.parent
        return False

    return [t for t in candidates if not has_ancestor_in_set(t)]


def flatten_tasks(tasks: list) -> list:
    result = []
    for task in tasks:
        result.append(task)
        result.extend(flatten_tasks(task.children))
    return result


def task_body_lines(task: Task) -> list[str]:
    if not task.body:
        return []
    body_indent = (task.indent or '') + get_indent_step()
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
