from os_utils import BackupManager, FileWriter
from parser import TaskParser
from .utils import flatten_tasks, task_body_lines, task_to_lines, block_rewrite_tasks, _block_lines


def has_changes(timed_tasks, untimed_tasks, original_lines, new_tasks, deleted_tasks=None, original_bodies=None) -> bool:
    if deleted_tasks:
        return True
    all_tasks = flatten_tasks(timed_tasks + untimed_tasks)
    if any(t.line_number == -1 for t in all_tasks):
        return True
    for task in all_tasks:
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
                    body_insert[task.line_number] = task_body_lines(task)

    delete_remove: set[int] = (
        _deleted_line_numbers(deleted_tasks, original_lines) if deleted_tasks else set()
    )

    br_tasks = block_rewrite_tasks(all_tasks)
    block_rewrites: dict[int, list[str]] = {t.line_number: task_to_lines(t) for t in br_tasks}
    block_remove: set[int] = set()
    for t in br_tasks:
        block_remove.update(_block_lines(t) - {t.line_number})

    to_remove = body_remove | delete_remove | block_remove

    if header_updates or to_remove or body_insert or block_rewrites:
        new_lines = []
        for i, line in enumerate(lines, 1):
            if i in block_rewrites:
                new_lines.extend(block_rewrites[i])
                continue
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
        lines.extend(task_to_lines(task))

    FileWriter.write_atomic(file_path, lines)

    all_tasks = TaskParser.parse_file(file_path)
    timed = [t for t in all_tasks if t.time is not None and t.parent is None]
    FileWriter.sort_timed_tasks(file_path, timed, all_tasks)
