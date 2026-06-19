from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Union

from config import get_task_config
from models import Task, TaskTime


@dataclass
class RawLine:
    raw: str  # exact line content, including newline


@dataclass
class TaskBlock:
    task: Task
    header: str       # exact header line; call refresh_header() after mutating task
    nodes: list = field(default_factory=list)  # list[Node], body in document order

    def refresh_header(self) -> None:
        self.header = self.task.to_line() + '\n'


Node = Union[RawLine, TaskBlock]


def serialize(nodes: list[Node]) -> str:
    parts = []
    for node in nodes:
        if isinstance(node, TaskBlock):
            parts.append(node.header)
            parts.append(serialize(node.nodes))
        else:
            parts.append(node.raw)
    return ''.join(parts)



def all_tasks(nodes: list) -> list[Task]:
    """Return all Task objects in document order (depth-first)."""
    result = []
    for node in nodes:
        if isinstance(node, TaskBlock):
            result.append(node.task)
            result.extend(all_tasks(node.nodes))
    return result


def _parse_task_from_line(line: str, line_number: int = -1) -> Task | None:
    config = get_task_config()
    match = re.search(config['checkbox_pattern'], line)
    if not match:
        return None

    indent = re.match(r'^(\s*)', line).group(1)
    status_char = match.group(1).strip()
    char_to_status = {
        char: status
        for status, chars in config['status_chars'].items()
        for char in chars
    }
    status = char_to_status.get(status_char)

    task_head = re.sub(config['checkbox_pattern'], '', line.strip()).strip()
    time_match = re.search(config['time_pattern'], task_head)
    task_time = None
    if time_match:
        parts = time_match.group(1).split('-')
        task_time = TaskTime(
            start=parts[0].strip(),
            end=parts[1].strip() if len(parts) >= 2 else None,
        )

    title = re.sub(config['time_pattern'], '', task_head).strip()
    return Task(title=title, status=status, time=task_time, line_number=line_number, indent=indent)


def parse_lines(lines: list[str]) -> list[Node]:
    """Parse a list of lines into an ordered node list."""
    top_level: list[Node] = []
    stack: list[tuple[int, TaskBlock]] = []  # (indent_len, block)

    def current_nodes() -> list[Node]:
        return stack[-1][1].nodes if stack else top_level

    for i, line in enumerate(lines):
        task = _parse_task_from_line(line, line_number=i + 1)
        if task is not None:
            indent_len = len(task.indent)
            while stack and stack[-1][0] >= indent_len:
                stack.pop()
            block = TaskBlock(task=task, header=line)
            current_nodes().append(block)
            stack.append((indent_len, block))
        elif not line.strip():
            # Blank line belongs to the preceding node: stored in current_nodes(),
            # which points to the preceding task's nodes when we are between tasks.
            # Leading blanks (before any task) land in top_level via current_nodes().
            current_nodes().append(RawLine(line))
        else:
            # non-task content: find deepest task with indent strictly less than this line
            line_indent_len = len(re.match(r'^(\s*)', line).group(1))
            owner_nodes = top_level
            for indent_len, block in reversed(stack):
                if indent_len < line_indent_len:
                    owner_nodes = block.nodes
                    break
            owner_nodes.append(RawLine(line))

    return top_level


def parse(file_path: str) -> list[Node]:
    """Parse a file into an ordered node list. serialize(parse(f)) == open(f).read()."""
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    return parse_lines(lines)
