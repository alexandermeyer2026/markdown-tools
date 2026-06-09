from os_utils import BackupManager, FileWriter
from parser import TaskParser
from .utils import flatten_tasks


def has_changes(timed_tasks, untimed_tasks, original_lines, new_tasks, deleted_tasks=None, original_bodies=None) -> bool:
    if new_tasks or deleted_tasks:
        return True
    for task in flatten_tasks(timed_tasks + untimed_tasks):
        if task.line_number > 0 and task.line_number in original_lines:
            if original_lines[task.line_number] != task.to_line():
                return True
        if original_bodies and task.line_number > 0 and task.line_number in original_bodies:
            if original_bodies[task.line_number] != task.body:
                return True
    return False


def _deleted_line_numbers(deleted_tasks, original_lines) -> set:
    """Return the set of 1-based line numbers to remove for each deleted task's block."""
    all_lns = sorted(original_lines.keys())
    to_remove: set[int] = set()
    for task in deleted_tasks:
        if task.line_number <= 0:
            continue
        task_indent = len(task.indent)
        block_end = all_lns[-1] if all_lns else task.line_number
        found = False
        for ln in all_lns:
            if found:
                orig = original_lines[ln]
                if len(orig) - len(orig.lstrip()) <= task_indent:
                    block_end = ln - 1
                    break
            elif ln == task.line_number:
                found = True
        to_remove.update(range(task.line_number, block_end + 1))
    return to_remove


def _body_lines(task) -> list[str]:
    if not task.body:
        return []
    body_indent = (task.indent or '') + '    '
    result = []
    for line in task.body.split('\n'):
        stripped = line.strip()
        result.append(body_indent + stripped + '\n' if stripped else '\n')
    return result


def save(file_path, directory, timed_tasks, untimed_tasks, original_lines, new_tasks, deleted_tasks=None, original_bodies=None):
    BackupManager.backup(file_path, directory)

    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    all_tasks = flatten_tasks(timed_tasks + untimed_tasks)

    header_updates = {
        task.line_number: task.to_line() + '\n'
        for task in all_tasks
        if task.line_number in original_lines and original_lines[task.line_number] != task.to_line()
    }

    body_remove: set[int] = set()
    body_insert: dict[int, list[str]] = {}
    if original_bodies:
        for task in all_tasks:
            if task.line_number > 0 and task.line_number in original_bodies:
                if original_bodies[task.line_number] != task.body:
                    body_remove.update(task.body_line_numbers)
                    body_insert[task.line_number] = _body_lines(task)

    delete_remove: set[int] = (
        _deleted_line_numbers(deleted_tasks, original_lines) if deleted_tasks else set()
    )

    to_remove = body_remove | delete_remove

    if header_updates or to_remove or body_insert:
        new_lines = []
        for i, line in enumerate(lines, 1):
            if i in header_updates:
                line = header_updates[i]
            if i in to_remove:
                continue
            new_lines.append(line)
            if i in body_insert:
                new_lines.extend(body_insert[i])
        lines = new_lines

    for task in new_tasks:
        if lines and lines[-1] != '\n':
            lines.append('\n')
        lines.append(task.to_line() + '\n')
        lines.extend(_body_lines(task))

    FileWriter.write_atomic(file_path, lines)

    all_tasks = TaskParser.parse_file(file_path)
    timed = [t for t in all_tasks if t.time is not None and t.parent is None]
    FileWriter.sort_timed_tasks(file_path, timed, all_tasks)
