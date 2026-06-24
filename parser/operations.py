from __future__ import annotations

from typing import Optional

from config import get_indent_step
from models.task import Task, TaskTime, status_char_map
from models.file import FieldRange, RawLine, TaskBlock, compute_field_ranges


def _refresh_ranges(block: TaskBlock) -> None:
    result = compute_field_ranges(block.header)
    if result is not None:
        block.checkbox_range, block.time_range, block.priority_range, block.title_range = result


def set_status(block: TaskBlock, status: str) -> str:
    """Splice the status character in the checkbox; update task.status."""
    char = status_char_map().get(status, '?')
    r = block.checkbox_range
    h = block.header
    block.header = h[:r.start] + char + h[r.end:]
    block.task.status = status
    block.checkbox_range = FieldRange(r.start, r.start + len(char))
    return block.header


def set_time(block: TaskBlock, new_time: Optional[TaskTime]) -> str:
    """Set, replace, or remove the time field; update task.time."""
    h = block.header

    if new_time is not None:
        new_text = new_time.to_str() + ' '
    else:
        new_text = ''

    if block.time_range is not None:
        r = block.time_range
        block.header = h[:r.start] + new_text + h[r.end:]
    elif new_time is not None:
        insert_at = (block.priority_range.start if block.priority_range is not None
                     else block.title_range.start)
        block.header = h[:insert_at] + new_text + h[insert_at:]

    block.task.time = new_time
    _refresh_ranges(block)
    return block.header


def set_title(block: TaskBlock, new_title: str) -> str:
    """Replace the title text; update task.title."""
    r = block.title_range
    h = block.header
    block.header = h[:r.start] + new_title + h[r.end:]
    block.task.title = new_title
    block.title_range = FieldRange(r.start, r.start + len(new_title))
    return block.header


def set_priority(block: TaskBlock, new_priority: Optional[str]) -> str:
    """Set, replace, or remove priority markers; update task.priority."""
    h = block.header

    if block.priority_range is not None:
        pri_start = block.priority_range.start
        pri_end = block.priority_range.end
        title_start = block.title_range.start
        if new_priority is not None:
            # Replace markers only; trailing space is between pri_end and title_start
            block.header = h[:pri_start] + new_priority + h[pri_end:]
        else:
            # Remove markers and the space that follows them
            block.header = h[:pri_start] + h[title_start:]
    elif new_priority is not None:
        insert_at = block.title_range.start
        block.header = h[:insert_at] + new_priority + ' ' + h[insert_at:]

    block.task.priority = new_priority
    _refresh_ranges(block)
    return block.header


def set_body_and_subtasks(block: TaskBlock, body: str | None, subtasks: list) -> None:
    """Replace body lines and subtask children; preserve trailing blank lines."""
    body_indent = (block.task.indent or '') + get_indent_step()

    trailing = []
    for node in reversed(block.nodes):
        if isinstance(node, RawLine) and not node.raw.strip():
            trailing.insert(0, node)
        else:
            break

    body_nodes = []
    if body:
        for line in body.split('\n'):
            stripped = line.strip()
            body_nodes.append(RawLine(body_indent + stripped + '\n') if stripped else RawLine('\n'))

    block.nodes[:] = body_nodes + list(subtasks) + trailing


def task_to_block(task: Task, body: str | None = None, subtask_blocks: list | None = None) -> TaskBlock:
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
            _refresh_ranges(child_block)
        nodes.append(child_block)
    header = task.to_line() + '\n'
    ranges = compute_field_ranges(header) or (None, None, None, None)
    cbx_r, time_r, pri_r, title_r = ranges
    return TaskBlock(task=task, header=header, nodes=nodes,
                     checkbox_range=cbx_r, time_range=time_r,
                     priority_range=pri_r, title_range=title_r)


def insert_task(nodes: list, task: Task) -> TaskBlock:
    """Append task as a new TaskBlock. Top-level tasks get a trailing blank line; subtasks get none."""
    is_subtask = bool(task.indent)

    header = task.to_line() + '\n'
    ranges = compute_field_ranges(header) or (None, None, None, None)
    cbx_r, time_r, pri_r, title_r = ranges
    block = TaskBlock(
        task=task,
        header=header,
        checkbox_range=cbx_r,
        time_range=time_r,
        priority_range=pri_r,
        title_range=title_r,
        nodes=[] if is_subtask else [RawLine('\n')],
    )
    nodes.append(block)
    return block
