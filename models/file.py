from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional, Union

from config import get_task_config, get_indent_step
from models.task import Task, TaskTime, status_char_map


_TAG_LINE_RE = re.compile(r'^\s*(#[\w-]+)(\s+#[\w-]+)*\s*$')


@dataclass
class FieldRange:
    """Inclusive start, exclusive end column offsets within a header line (trailing newline excluded)."""
    start: int
    end: int

    def slice(self, s: str) -> str:
        return s[self.start:self.end]


@dataclass
class RawLine:
    raw: str  # exact line content, including newline


@dataclass
class TaskBlock:
    task: Task
    header: str       # exact header line; mutate only via set_* methods
    nodes: list = field(default_factory=list)  # list[Node], body in document order
    tag_node: Optional[RawLine] = field(default=None)  # RawLine holding the tag line, if any
    checkbox_range: Optional[FieldRange] = field(default=None)
    time_range: Optional[FieldRange] = field(default=None)
    priority_range: Optional[FieldRange] = field(default=None)
    title_range: Optional[FieldRange] = field(default=None)

    # ── Surgical field ops ────────────────────────────────────────────────────

    def _refresh_ranges(self) -> None:
        result = compute_field_ranges(self.header)
        if result is not None:
            self.checkbox_range, self.time_range, self.priority_range, self.title_range = result

    def set_status(self, status: str) -> None:
        char = status_char_map().get(status, '?')
        r = self.checkbox_range
        self.header = self.header[:r.start] + char + self.header[r.end:]
        self.task.status = status
        self.checkbox_range = FieldRange(r.start, r.start + len(char))

    def set_time(self, new_time: Optional[TaskTime]) -> None:
        new_text = new_time.to_str() + ' ' if new_time is not None else ''
        if self.time_range is not None:
            r = self.time_range
            self.header = self.header[:r.start] + new_text + self.header[r.end:]
        elif new_time is not None:
            insert_at = (self.priority_range.start if self.priority_range is not None
                         else self.title_range.start)
            self.header = self.header[:insert_at] + new_text + self.header[insert_at:]
        self.task.time = new_time
        self._refresh_ranges()

    def set_title(self, new_title: str) -> None:
        r = self.title_range
        self.header = self.header[:r.start] + new_title + self.header[r.end:]
        self.task.title = new_title
        self.title_range = FieldRange(r.start, r.start + len(new_title))

    def set_priority(self, new_priority: Optional[str]) -> None:
        if self.priority_range is not None:
            pri_start = self.priority_range.start
            pri_end = self.priority_range.end
            title_start = self.title_range.start
            if new_priority is not None:
                self.header = self.header[:pri_start] + new_priority + self.header[pri_end:]
            else:
                self.header = self.header[:pri_start] + self.header[title_start:]
        elif new_priority is not None:
            insert_at = self.title_range.start
            self.header = self.header[:insert_at] + new_priority + ' ' + self.header[insert_at:]
        self.task.priority = new_priority
        self._refresh_ranges()

    def set_body_and_subtasks(self, body: str | None, subtasks: list) -> None:
        """Replace body lines and subtask children; preserve trailing blank lines."""
        body_indent = (self.task.indent or '') + get_indent_step()
        trailing = []
        for node in reversed(self.nodes):
            if isinstance(node, RawLine) and not node.raw.strip():
                trailing.insert(0, node)
            else:
                break
        body_nodes = []
        if body:
            for line in body.split('\n'):
                stripped = line.strip()
                body_nodes.append(RawLine(body_indent + stripped + '\n') if stripped else RawLine('\n'))
        self.nodes[:] = body_nodes + list(subtasks) + trailing

    @classmethod
    def from_task(cls, task: Task, body: str | None = None,
                  subtask_blocks: list | None = None) -> TaskBlock:
        """Build a new TaskBlock from a Task with optional body text and child blocks."""
        indent_step = get_indent_step()
        nodes = []
        if body:
            body_indent = (task.indent or '') + indent_step
            for line in body.split('\n'):
                stripped = line.strip()
                nodes.append(RawLine(body_indent + stripped + '\n') if stripped else RawLine('\n'))
        for child_block in (subtask_blocks or []):
            expected_indent = (task.indent or '') + indent_step
            if child_block.task.indent != expected_indent:
                old_indent = child_block.task.indent or ''
                child_block.header = expected_indent + child_block.header[len(old_indent):]
                child_block.task.indent = expected_indent
                child_block._refresh_ranges()
            nodes.append(child_block)
        header = task.to_line() + '\n'
        ranges = compute_field_ranges(header) or (None, None, None, None)
        cbx_r, time_r, pri_r, title_r = ranges
        return cls(task=task, header=header, nodes=nodes,
                   checkbox_range=cbx_r, time_range=time_r,
                   priority_range=pri_r, title_range=title_r)

    # ── Tags ──────────────────────────────────────────────────────────────────

    def refresh_tags(self) -> None:
        """Sync task.tags back to the body. Call after mutating task.tags."""
        if self.task.tags:
            tag_content = ' '.join(f'#{t}' for t in self.task.tags)
            if self.tag_node is not None:
                existing_indent = re.match(r'^(\s*)', self.tag_node.raw).group(1)
                self.tag_node.raw = existing_indent + tag_content + '\n'
            else:
                tag_indent = self.task.indent + '  '
                self.tag_node = RawLine(tag_indent + tag_content + '\n')
                self.nodes.append(self.tag_node)
        else:
            if self.tag_node is not None:
                self.nodes[:] = [n for n in self.nodes if n is not self.tag_node]
                self.tag_node = None


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


def compute_field_ranges(line: str) -> tuple[FieldRange, Optional[FieldRange], Optional[FieldRange], FieldRange] | None:
    """
    Compute column offsets for each field in a task header line.
    Returns (checkbox_range, time_range, priority_range, title_range) or None if not a task line.
    """
    config = get_task_config()
    cbx_match = re.search(config['checkbox_pattern'], line)
    if not cbx_match:
        return None

    line_body = line.rstrip('\n')
    checkbox_range = FieldRange(cbx_match.start(1), cbx_match.end(1))

    content_offset = cbx_match.end()
    if content_offset < len(line_body) and line_body[content_offset] == ' ':
        content_offset += 1

    content = line_body[content_offset:]
    time_match = re.search(config['time_pattern'], content)
    if time_match:
        time_range: Optional[FieldRange] = FieldRange(content_offset + time_match.start(), content_offset + time_match.end())
        after_time_offset = content_offset + time_match.end()
    else:
        time_range = None
        after_time_offset = content_offset

    after_time = line_body[after_time_offset:]
    priority_match = re.match(r'^(!{1,3})\s+(.*)', after_time)
    if priority_match:
        priority_range: Optional[FieldRange] = FieldRange(after_time_offset + priority_match.start(1), after_time_offset + priority_match.end(1))
        title_offset = after_time_offset + priority_match.start(2)
    else:
        priority_range = None
        title_offset = after_time_offset

    title_range = FieldRange(title_offset, len(line_body))
    return checkbox_range, time_range, priority_range, title_range


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
    priority = None
    priority_match = re.match(r'^(!{1,3})\s+(.*)', title)
    if priority_match:
        priority = priority_match.group(1)
        title = priority_match.group(2)
    return Task(title=title, status=status, time=task_time, line_number=line_number, indent=indent, priority=priority)


def _extract_tags(nodes: list[Node]) -> None:
    """Walk the tree and populate task.tags + tag_node from dedicated tag lines."""
    for node in nodes:
        if not isinstance(node, TaskBlock):
            continue
        for child in node.nodes:
            if isinstance(child, RawLine) and _TAG_LINE_RE.match(child.raw):
                node.task.tags = re.findall(r'#([\w-]+)', child.raw)
                node.tag_node = child
                break
        _extract_tags(node.nodes)


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
            ranges = compute_field_ranges(line)
            cbx_r, time_r, pri_r, title_r = ranges
            block = TaskBlock(
                task=task,
                header=line,
                checkbox_range=cbx_r,
                time_range=time_r,
                priority_range=pri_r,
                title_range=title_r,
            )
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

    _extract_tags(top_level)
    return top_level


def parse(file_path: str) -> list[Node]:
    """Parse a file into an ordered node list. serialize(parse(f)) == open(f).read()."""
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    return parse_lines(lines)


class File:
    def __init__(self, path: str):
        self.path = path
        try:
            with open(path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            self.nodes: list[Node] = parse_lines(lines)
        except FileNotFoundError:
            self.nodes = []


def insert_task(nodes: list, task: Task) -> TaskBlock:
    """Append task as a new TaskBlock. Top-level tasks get a trailing blank line; subtasks get none."""
    block = TaskBlock.from_task(task)
    if not task.indent:
        block.nodes.append(RawLine('\n'))
    nodes.append(block)
    return block
