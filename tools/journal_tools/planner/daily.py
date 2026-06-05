from os_utils import BackupManager, FileWriter
from parser import TaskParser
from .utils import flatten_tasks


def has_changes(timed_tasks, untimed_tasks, original_lines, new_tasks) -> bool:
    if new_tasks:
        return True
    for task in flatten_tasks(timed_tasks + untimed_tasks):
        if task.line_number > 0 and task.line_number in original_lines:
            if original_lines[task.line_number] != task.to_line():
                return True
    return False


def save(file_path, directory, timed_tasks, untimed_tasks, original_lines, new_tasks):
    BackupManager.backup(file_path, directory)

    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    for task in flatten_tasks(timed_tasks + untimed_tasks):
        if task.line_number in original_lines and original_lines[task.line_number] != task.to_line():
            lines[task.line_number - 1] = task.to_line() + '\n'

    for task in new_tasks:
        if lines and lines[-1] != '\n':
            lines.append('\n')
        lines.append(task.to_line() + '\n')

    FileWriter.write_atomic(file_path, lines)

    all_tasks = TaskParser.parse_file(file_path)
    timed = [t for t in all_tasks if t.time is not None and t.parent is None]
    FileWriter.sort_timed_tasks(file_path, timed, all_tasks)
