from __future__ import annotations

import os


def task_block_end(task: Task, sorted_tasks: list, total_lines: int) -> int:
    """Return the 0-based exclusive end index of task's block in a file."""
    task_indent = len(task.indent)
    found = False
    for t in sorted_tasks:
        if found:
            if len(t.indent) <= task_indent:
                return t.line_number - 1
        elif t.line_number == task.line_number:
            found = True
    return total_lines


class FileWriter:

    @staticmethod
    def cut_task(file_path: str, task: Task, all_tasks: list[Task]) -> list[str]:
        """Remove task's block from file and return the removed lines (with newlines)."""
        sorted_tasks = sorted(all_tasks, key=lambda t: t.line_number)

        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        start = task.line_number - 1
        end = task_block_end(task, sorted_tasks, len(lines))

        block = lines[start:end]
        remaining = lines[:start] + lines[end:]

        FileWriter._write_atomic(file_path, remaining)
        return block

    @staticmethod
    def paste_task(file_path: str, block: list[str]) -> None:
        """Append a task block to the end of a file, preceded by a blank line."""
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        if lines:
            if not lines[-1].endswith('\n'):
                lines[-1] += '\n'
            if lines[-1] != '\n':
                lines.append('\n')

        FileWriter._write_atomic(file_path, lines + block)

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

    @staticmethod
    def touch(file_path: str) -> None:
        """Create an empty file if it does not already exist."""
        open(file_path, 'a').close()

    @staticmethod
    def write_lines(file_path: str, lines: list[str]) -> None:
        """Write raw lines atomically to file_path."""
        FileWriter._write_atomic(file_path, lines)

    @staticmethod
    def _write_atomic(file_path: str, lines: list[str]) -> None:
        tmp = file_path + '.tmp'
        try:
            with open(tmp, 'w', encoding='utf-8') as f:
                f.writelines(lines)
                if lines and not lines[-1].endswith('\n'):
                    f.write('\n')
            os.replace(tmp, file_path)
        except Exception:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise
