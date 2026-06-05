from os_utils import BackupManager, FileWriter
from parser import TaskParser
from .utils import flatten_tasks


def has_changes(timed_tasks, untimed_tasks, original_lines, new_tasks, deleted_tasks=None) -> bool:
    if new_tasks or deleted_tasks:
        return True
    for task in flatten_tasks(timed_tasks + untimed_tasks):
        if task.line_number > 0 and task.line_number in original_lines:
            if original_lines[task.line_number] != task.to_line():
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


def save(file_path, directory, timed_tasks, untimed_tasks, original_lines, new_tasks, deleted_tasks=None):
    BackupManager.backup(file_path, directory)

    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    for task in flatten_tasks(timed_tasks + untimed_tasks):
        if task.line_number in original_lines and original_lines[task.line_number] != task.to_line():
            lines[task.line_number - 1] = task.to_line() + '\n'

    if deleted_tasks:
        remove = _deleted_line_numbers(deleted_tasks, original_lines)
        lines = [ln for i, ln in enumerate(lines, 1) if i not in remove]

    for task in new_tasks:
        if lines and lines[-1] != '\n':
            lines.append('\n')
        lines.append(task.to_line() + '\n')

    FileWriter.write_atomic(file_path, lines)

    all_tasks = TaskParser.parse_file(file_path)
    timed = [t for t in all_tasks if t.time is not None and t.parent is None]
    FileWriter.sort_timed_tasks(file_path, timed, all_tasks)
