import datetime
import os

from models import Task
from os_utils import FileFinder
import copy

from models.file import (
    TaskBlock, parse,
    append_block, remove_block, sort_timed_nodes,
    tab_task, shift_tab_task, move_block_in_nodes,
    insert_task as _insert_task,
    detach_child_blocks,
    find_block as _find_block,
)


def _file_stamp(path) -> 'tuple[float, int] | None':
    """Return (mtime, size) identifying a file's on-disk state, or None if absent."""
    if not path or not os.path.exists(path):
        return None
    st = os.stat(path)
    return (st.st_mtime, st.st_size)


class DayCache:
    def __init__(self, file_path, nodes, stamp=None):
        self.file_path = file_path
        self.nodes = nodes
        self.stamp = stamp  # (mtime, size) of file_path when last read/written
        self._version = 0
        self._saved_version = 0
        self._cp_nodes = None
        self._cp_saved_version = 0
        self._cp_version = 0

    @property
    def has_changes(self) -> bool:
        return self._version != self._saved_version

    def _bump(self) -> None:
        self._version += 1

    def mark_saved(self) -> None:
        """Record a successful write: sync the saved version and file stamp."""
        self._saved_version = self._version
        self.stamp = _file_stamp(self.file_path)

    @property
    def task_list(self) -> list:
        return [n for n in self.nodes if isinstance(n, TaskBlock)]

    def find_block(self, task) -> 'TaskBlock | None':
        return _find_block(self.nodes, task)

    # ── Checkpointing ─────────────────────────────────────────────────────────

    def checkpoint(self) -> None:
        """Snapshot current state; restore_checkpoint() returns here."""
        self._cp_nodes = copy.deepcopy(self.nodes)
        self._cp_saved_version = self._saved_version
        self._cp_version = self._version

    def update_checkpoint(self) -> None:
        """Advance checkpoint after a ctrl+s save so discard returns to saved state."""
        self._cp_nodes = copy.deepcopy(self.nodes)
        self._cp_saved_version = self._saved_version
        self._cp_version = self._version

    def restore_checkpoint(self) -> None:
        """Revert to the state when checkpoint() was last called."""
        if self._cp_nodes is None:
            self.discard()
            return
        self.nodes = copy.deepcopy(self._cp_nodes)
        self._saved_version = self._cp_saved_version
        self._version = self._cp_version

    def discard(self) -> None:
        """Reload from disk, discarding all in-memory changes."""
        if self.file_path and os.path.exists(self.file_path):
            self.nodes = parse(self.file_path)
        else:
            self.nodes = []
        self.stamp = _file_stamp(self.file_path)
        self._version = self._saved_version

    # ── Mutation API ──────────────────────────────────────────────────────────

    def set_status(self, task, status: str) -> None:
        if task.status == status:
            return
        block = self.find_block(task)
        if block is None:
            raise ValueError(f"Block not found for task {task.title!r} — task may not belong to this DayCache")
        block.set_status(status)
        self._bump()

    def set_priority(self, task, priority) -> None:
        if task.priority == priority:
            return
        block = self.find_block(task)
        if block is None:
            raise ValueError(f"Block not found for task {task.title!r} — task may not belong to this DayCache")
        block.set_priority(priority)
        self._bump()

    def set_time(self, task, time) -> None:
        if task.time == time:
            return
        block = self.find_block(task)
        if block is None:
            raise ValueError(f"Block not found for task {task.title!r} — task may not belong to this DayCache")
        block.set_time(time)
        sort_timed_nodes(self.nodes)
        self._bump()

    def update_task(self, task, title: str, status: str, time, body, subtasks) -> None:
        block = self.find_block(task)
        if block is None:
            raise ValueError(f"Block not found for task {task.title!r} — task may not belong to this DayCache")
        block.set_status(status)
        block.set_time(time)
        block.set_title(title)
        block.set_body_and_subtasks(body, subtasks)
        sort_timed_nodes(self.nodes)
        self._bump()

    def add_block(self, block: TaskBlock) -> None:
        append_block(self.nodes, block)
        self._bump()

    def insert_task(self, task, body: str | None = None,
                    subtasks: list | None = None) -> TaskBlock:
        block = _insert_task(self.nodes, task, body, subtasks)
        self._bump()
        return block

    def remove_block(self, block: TaskBlock) -> None:
        remove_block(self.nodes, block)
        self._bump()

    def move_block_to(self, block: TaskBlock, dst: 'DayCache') -> None:
        remove_block(self.nodes, block)
        self._bump()
        append_block(dst.nodes, block)
        if block.task.time:
            sort_timed_nodes(dst.nodes)
        dst._bump()

    def carry_subtasks_to(self, task, dst: 'DayCache') -> bool:
        """Move unfinished subtasks to a same-title block in dst. Returns True if any carried."""
        block = self.find_block(task)
        if block is None:
            return False
        child_blocks = [n for n in block.nodes if isinstance(n, TaskBlock)]
        unfinished = [b for b in child_blocks if b.task.status not in ("done", "failed", "started")]
        if not unfinished:
            return False
        detach_child_blocks(block, unfinished)
        self._bump()
        new_task = Task(title=task.title, status="todo", time=None, line_number=-1, indent="")
        new_block = TaskBlock.from_task(new_task, subtask_blocks=unfinished)
        append_block(dst.nodes, new_block)
        dst._bump()
        return True

    def tab_task_block(self, task) -> bool:
        result = tab_task(self.nodes, task)
        if result:
            self._bump()
        return result

    def shift_tab_task_block(self, task) -> bool:
        result = shift_tab_task(self.nodes, task)
        if result:
            self._bump()
        return result

    def reorder_block(self, task, direction: int) -> bool:
        result = move_block_in_nodes(self.nodes, task, direction)
        if result:
            self._bump()
        return result


class PlannerState:
    def __init__(self, directory: str):
        self.directory = directory
        self._days: dict[str, DayCache] = {}

    @property
    def days(self) -> dict[str, DayCache]:
        return self._days

    def load_day(self, day: datetime.date) -> DayCache:
        key = day.isoformat()
        files = FileFinder.find_journal_files(
            self.directory, date_from=day, date_to=day
        )
        fp = files[0] if files else None
        if key not in self._days:
            self._load_into_state(key, fp)
        else:
            self._refresh_if_stale(key, fp)
        return self._days[key]

    def load_file(self, file_path: str, date: datetime.date | None = None) -> tuple[str, DayCache]:
        if date is not None:
            key = date.isoformat()
        else:
            try:
                key = FileFinder.get_journal_file_date(file_path).isoformat()
            except (ValueError, AttributeError):
                key = file_path
        if key not in self._days:
            self._load_into_state(key, file_path)
        else:
            self._refresh_if_stale(key, file_path)
        return key, self._days[key]

    def reload_day_by_key(self, key: str, new_file_path: str | None = None) -> None:
        existing = self._days.get(key)
        fp = new_file_path if new_file_path is not None else (
            existing.file_path if existing else None
        )
        self._load_into_state(key, fp)

    def _refresh_if_stale(self, key: str, file_path: str | None) -> None:
        """Re-read a cached day from disk when it holds no unsaved edits and the
        file changed underneath it (or a file now exists where none did).

        Days with in-memory changes are left untouched so edits are never
        silently discarded — the dashboard/week/day views share one cache, and
        only this refresh keeps a clean day from overwriting a newer file on save.
        """
        day = self._days.get(key)
        if day is None or day.has_changes:
            return
        if file_path != day.file_path or _file_stamp(file_path) != day.stamp:
            self._load_into_state(key, file_path)

    def _load_into_state(self, key: str, file_path: str | None) -> None:
        if file_path and os.path.exists(file_path):
            nodes = parse(file_path)
        else:
            nodes = []
        self._days[key] = DayCache(
            file_path=file_path, nodes=nodes, stamp=_file_stamp(file_path)
        )


class WeekState:
    def __init__(self, week_days: list, planner: PlannerState):
        self.week_days = week_days
        self._planner = planner

    @property
    def cache(self) -> dict[str, DayCache]:
        return self._planner.days

    @property
    def directory(self) -> str:
        return self._planner.directory

    def day(self, col: int) -> DayCache:
        return self._planner.days[self.week_days[col].isoformat()]
