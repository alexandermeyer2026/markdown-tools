import re

from config import get_task_config
from models import Task, TaskTime


class TaskParser:
    _config = None
    _char_to_status_map = None

    @classmethod
    def _get_config(cls) -> dict:
        if cls._config is None:
            cls._config = get_task_config()
        return cls._config

    @classmethod
    def _char_to_status(cls) -> dict:
        if cls._char_to_status_map is None:
            cls._char_to_status_map = {
                char: status
                for status, chars in cls._get_config()['status_chars'].items()
                for char in chars
            }
        return cls._char_to_status_map

    @classmethod
    def parse_file(cls, file_path) -> list[Task]:
        config = cls._get_config()
        checkbox_pattern = config['checkbox_pattern']
        time_pattern = config['time_pattern']
        char_to_status = cls._char_to_status()

        tasks: list[Task] = []
        stack: list[Task] = []  # ancestor tasks ordered by increasing indent depth

        with open(file_path, 'r', encoding='utf-8') as f:
            for line_number, line in enumerate(f, 1):
                match = re.search(checkbox_pattern, line)

                if match:
                    indent_match = re.match(r'^(\s*)', line)
                    indent = indent_match.group(1) if indent_match else ''

                    status_char = match.group(1).strip()
                    status = char_to_status.get(status_char)
                    if status is None and status_char:
                        print(f'Unknown status character: {status_char}')

                    task_head = re.sub(checkbox_pattern, '', line.strip()).strip()

                    time_match = re.search(time_pattern, task_head)
                    task_time = None
                    if time_match:
                        time_strings = time_match.group(1).split('-')
                        task_time = TaskTime(
                            start=time_strings[0].strip(),
                            end=time_strings[1].strip() if len(time_strings) >= 2 else None,
                        )

                    title = re.sub(time_pattern, '', task_head).strip()

                    task = Task(
                        title=title,
                        status=status,
                        time=task_time,
                        line_number=line_number,
                        indent=indent,
                    )

                    while stack and len(stack[-1].indent) >= len(indent):
                        stack.pop()
                    if stack:
                        task.parent = stack[-1]
                        stack[-1].children.append(task)
                    stack.append(task)
                    tasks.append(task)

                else:
                    if not stack:
                        continue

                    content = line.rstrip('\n')

                    if not content.strip():
                        owner = stack[-1]
                    else:
                        indent_match = re.match(r'^(\s*)', content)
                        line_indent = indent_match.group(1) if indent_match else ''
                        owner = None
                        for candidate in reversed(stack):
                            if len(candidate.indent) < len(line_indent):
                                owner = candidate
                                break
                        if owner is None:
                            continue

                    owner.body = (owner.body + '\n' + content) if owner.body is not None else content

        return tasks
