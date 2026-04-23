import os

from models.task import Task


class FileWriter:

    @staticmethod
    def cut_task(file_path: str, task: Task, all_tasks: list[Task]) -> list[str]:
        """Remove task's block from file and return the removed lines (with newlines)."""
        sorted_tasks = sorted(all_tasks, key=lambda t: t.line_number)
        task_indent_len = len(task.indent)

        next_boundary = None
        found = False
        for t in sorted_tasks:
            if found:
                if len(t.indent) <= task_indent_len:
                    next_boundary = t.line_number
                    break
            elif t.line_number == task.line_number:
                found = True

        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        start = task.line_number - 1  # convert to 0-based
        end = (next_boundary - 1) if next_boundary is not None else len(lines)

        block = lines[start:end]
        remaining = lines[:start] + lines[end:]

        _write_atomic(file_path, remaining)
        return block

    @staticmethod
    def paste_task(file_path: str, block: list[str]) -> None:
        """Append a task block to the end of a file."""
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        # Ensure the file ends with a newline before appending
        if lines and not lines[-1].endswith('\n'):
            lines[-1] += '\n'

        _write_atomic(file_path, lines + block)

    @staticmethod
    def move_task(from_path: str, to_path: str, task: Task, all_tasks: list[Task]) -> None:
        """Cut task from one file and paste it at the end of another."""
        block = FileWriter.cut_task(from_path, task, all_tasks)
        FileWriter.paste_task(to_path, block)

    @staticmethod
    def reindent_block(block: list[str], from_indent: str, to_indent: str) -> list[str]:
        """Replace the leading indent prefix on every line in the block."""
        result = []
        for line in block:
            if line.startswith(from_indent):
                result.append(to_indent + line[len(from_indent):])
            else:
                result.append(line)
        return result


def _write_atomic(file_path: str, lines: list[str]) -> None:
    tmp = file_path + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            f.writelines(lines)
        os.replace(tmp, file_path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
