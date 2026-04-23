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
    def sort_timed_tasks(file_path: str, timed_tasks: list[Task], all_tasks: list[Task]) -> None:
        """Sort timed tasks by start time in place; only tasks sharing the same parent are sorted together."""
        groups: dict[int, list[Task]] = {}
        for task in timed_tasks:
            groups.setdefault(id(task.parent), []).append(task)

        all_sorted = sorted(all_tasks, key=lambda t: t.line_number)

        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        def block_range(task: Task) -> tuple[int, int]:
            indent_len = len(task.indent)
            next_boundary = None
            found = False
            for t in all_sorted:
                if found:
                    if len(t.indent) <= indent_len:
                        next_boundary = t.line_number
                        break
                elif t.line_number == task.line_number:
                    found = True
            start = task.line_number - 1
            end = (next_boundary - 1) if next_boundary is not None else len(lines)
            return start, end

        all_assignments = []
        for group in groups.values():
            if len(group) < 2:
                continue
            ranges = [block_range(t) for t in group]
            blocks = [lines[s:e] for s, e in ranges]
            position_order = sorted(range(len(group)), key=lambda i: ranges[i][0])
            time_order = sorted(range(len(group)), key=lambda i: _time_to_minutes(group[i].time.start))
            for k in range(len(group)):
                all_assignments.append((ranges[position_order[k]], blocks[time_order[k]]))

        if not all_assignments:
            return

        new_lines = list(lines)
        for (s, e), block in sorted(all_assignments, key=lambda x: x[0][0], reverse=True):
            new_lines[s:e] = block

        _write_atomic(file_path, new_lines)

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


def _time_to_minutes(time_str: str) -> int:
    h, m = time_str.split(':')
    return int(h) * 60 + int(m)


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
