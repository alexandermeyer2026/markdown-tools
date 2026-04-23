import re

from config import get_task_config
from models import Task, TaskTime


class TaskParser:
    _config = None

    @classmethod
    def _get_config(cls) -> dict:
        if cls._config is None:
            cls._config = get_task_config()
        return cls._config

    @classmethod
    def _char_to_status(cls) -> dict:
        return {
            char: status
            for status, chars in cls._get_config()['status_chars'].items()
            for char in chars
        }

    @classmethod
    def parse_file(cls, file_path) -> list[Task]:
        config = cls._get_config()
        checkbox_pattern = config['checkbox_pattern']
        time_pattern = config['time_pattern']
        char_to_status = cls._char_to_status()

        tasks = []
        with open(file_path, 'r') as f:
            for line_number, line in enumerate(f, 1):
                match = re.search(checkbox_pattern, line)
                if not match:
                    continue

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

                tasks.append(Task(
                    title=title,
                    status=status,
                    time=task_time,
                    line_number=line_number,
                    indent=indent,
                ))

        return tasks
