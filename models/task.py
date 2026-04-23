from dataclasses import dataclass
from typing import Optional


@dataclass
class TaskTime:
    start: str
    end: Optional[str] = None

    def to_str(self) -> str:
        if self.end:
            return f"{self.start}-{self.end}"
        return self.start


@dataclass
class Task:
    title: str
    status: Optional[str]
    time: Optional[TaskTime]
    line_number: int
    indent: str = ''

    STATUS_CHAR = {
        'todo': ' ',
        'in progress': '…',
        'done': 'x',
        'failed': '–',
        'started': '~',
    }

    def to_line(self) -> str:
        status_char = self.STATUS_CHAR.get(self.status, '?')
        line = f"{self.indent}- [{status_char}]"
        if self.time:
            line += f" {self.time.to_str()}"
        line += f" {self.title}"
        return line
