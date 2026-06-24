import os

from models import Task, get_minutes
from models.file import Node, serialize


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

        FileWriter.write_atomic(file_path,remaining)
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

        FileWriter.write_atomic(file_path, lines + block)

    @staticmethod
    def move_task(from_path: str, to_path: str, task: Task, all_tasks: list[Task]) -> None:
        """Cut task from one file and paste it at the end of another."""
        block = FileWriter.cut_task(from_path, task, all_tasks)
        FileWriter.paste_task(to_path, block)

    @staticmethod
    def sort_timed_tasks(file_path: str, timed_tasks: list[Task], all_tasks: list[Task]) -> None:
        """Sort timed tasks by start time in place; only tasks sharing the same parent are sorted together."""
        all_sorted_by_line = sorted(all_tasks, key=lambda t: t.line_number)

        def _parent_key(task: Task) -> int:
            depth = len(task.indent)
            idx = next((i for i, t in enumerate(all_sorted_by_line) if t is task), -1)
            for i in range(idx - 1, -1, -1):
                if len(all_sorted_by_line[i].indent) < depth:
                    return id(all_sorted_by_line[i])
            return -1

        groups: dict[int, list[Task]] = {}
        for task in timed_tasks:
            groups.setdefault(_parent_key(task), []).append(task)

        all_sorted = sorted(all_tasks, key=lambda t: t.line_number)

        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        def block_range(task: Task) -> tuple[int, int]:
            start = task.line_number - 1
            end = task_block_end(task, all_sorted, len(lines))
            while end > start and lines[end - 1].strip() == '':
                end -= 1
            return start, end

        all_assignments = []
        for group in groups.values():
            if len(group) < 2:
                continue
            ranges = [block_range(t) for t in group]
            blocks = [lines[s:e] for s, e in ranges]
            position_order = sorted(range(len(group)), key=lambda i: ranges[i][0])
            time_order = sorted(range(len(group)), key=lambda i: get_minutes(group[i].time.start))
            for k in range(len(group)):
                all_assignments.append((ranges[position_order[k]], blocks[time_order[k]]))

        if not all_assignments:
            return

        new_lines = list(lines)
        for (s, e), block in sorted(all_assignments, key=lambda x: x[0][0], reverse=True):
            new_lines[s:e] = block

        FileWriter.write_atomic(file_path, new_lines)

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
    def write_nodes(file_path: str, nodes: list[Node]) -> None:
        """Serialize a node tree and write it atomically to file_path."""
        FileWriter.write_atomic(file_path, serialize(nodes).splitlines(keepends=True))

    @staticmethod
    def write_atomic(file_path: str, lines: list[str]) -> None:
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
