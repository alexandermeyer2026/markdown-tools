from models import Task, get_minutes
from models.file import TaskBlock

# Rotation order for the "!" keybind: none → ! → !! → !!! → none.
PRIORITY_CYCLE: list = [None, "!", "!!", "!!!"]


def next_priority(current) -> str | None:
    """Return the next priority in the rotation, wrapping !!! back to none."""
    idx = PRIORITY_CYCLE.index(current) if current in PRIORITY_CYCLE else 0
    return PRIORITY_CYCLE[(idx + 1) % len(PRIORITY_CYCLE)]


def flatten_tasks(blocks: list) -> list[Task]:
    """Return all Tasks in document order (DFS) from a list of TaskBlocks."""
    result = []
    for block in blocks:
        if isinstance(block, TaskBlock):
            result.append(block.task)
            result.extend(flatten_tasks([n for n in block.nodes if isinstance(n, TaskBlock)]))
    return result


def _block_with_depth(block: TaskBlock, depth: int) -> list[tuple]:
    result = [(block.task, depth)]
    for child_block in [n for n in block.nodes if isinstance(n, TaskBlock)]:
        result.extend(_block_with_depth(child_block, depth + 1))
    return result


def week_expanded(blocks: list) -> list[tuple]:
    """Flatten top-level blocks for week display, timed first. Returns (task, depth) pairs."""
    timed = sorted([b for b in blocks if b.task.time], key=lambda b: get_minutes(b.task.time.start))
    untimed = [b for b in blocks if not b.task.time]
    result = []
    for block in timed + untimed:
        result.extend(_block_with_depth(block, 0))
    return result
