from __future__ import annotations

from dataclasses import dataclass, field
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
    body: Optional[str] = None
    parent: Optional[Task] = field(default=None, compare=False, repr=False)
    children: list[Task] = field(default_factory=list, compare=False, repr=False)

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
