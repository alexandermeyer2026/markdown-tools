import datetime
import os

from models import Task
from os_utils import FileFinder
import copy

from models.file import RawLine, TaskBlock, compute_field_ranges, parse
import parser.operations as ops


def _find_block_in(nodes: list, task) -> 'TaskBlock | None':
    for node in nodes:
        if isinstance(node, TaskBlock):
            if node.task is task:
                return node
            result = _find_block_in(node.nodes, task)
            if result is not None:
                return result
    return None


class DayCache:
    def __init__(self, file_path, nodes):
        self.file_path = file_path
        self.nodes = nodes
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

    @property
    def task_list(self) -> list:
        return [n for n in self.nodes if isinstance(n, TaskBlock)]

    def find_block(self, task) -> 'TaskBlock | None':
        return _find_block_in(self.nodes, task)

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
        self._version = self._saved_version

    # ── Mutation API ──────────────────────────────────────────────────────────

    def set_status(self, task, status: str) -> None:
        if task.status == status:
            return
        block = self.find_block(task)
        if block:
            ops.set_status(block, status)
        else:
            task.status = status
        self._bump()

    def set_time(self, task, time) -> None:
        from .weekly import sort_timed_nodes
        if task.time == time:
            return
        block = self.find_block(task)
        if block:
            ops.set_time(block, time)
        else:
            task.time = time
        sort_timed_nodes(self.nodes)
        self._bump()

    def update_task(self, task, title: str, status: str, time, body, subtasks) -> None:
        from .weekly import sort_timed_nodes, task_to_block
        block = self.find_block(task)
        if block is None:
            task.title = title
            task.status = status
            task.time = time
        else:
            ops.set_status(block, status)
            ops.set_time(block, time)
            ops.set_title(block, title)
            # Trailing blank RawLines are inter-task gaps owned by this block;
            # they are not body content and must survive an edit unchanged.
            trailing = []
            for node in reversed(block.nodes):
                if isinstance(node, RawLine) and not node.raw.strip():
                    trailing.insert(0, node)
                else:
                    break
            rebuilt = task_to_block(task, body, subtasks)
            # task_to_block may emit a trailing blank when body ends with \n;
            # remove it so we restore exactly the original inter-task spacing.
            while rebuilt.nodes and isinstance(rebuilt.nodes[-1], RawLine) and not rebuilt.nodes[-1].raw.strip():
                rebuilt.nodes.pop()
            block.nodes[:] = rebuilt.nodes + trailing
        sort_timed_nodes(self.nodes)
        self._bump()

    def add_block(self, block: TaskBlock) -> None:
        from .weekly import append_block
        append_block(self.nodes, block)
        self._bump()

    def remove_block(self, block: TaskBlock) -> None:
        from .weekly import remove_block as _remove
        _remove(self.nodes, block)
        self._bump()

    def move_block_to(self, block: TaskBlock, dst: 'DayCache') -> None:
        from .weekly import append_block, remove_block as _remove, sort_timed_nodes
        _remove(self.nodes, block)
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
        unfinished_ids = {id(b) for b in unfinished}
        block.nodes[:] = [
            n for n in block.nodes
            if not (isinstance(n, TaskBlock) and id(n) in unfinished_ids)
        ]
        self._bump()
        new_task = Task(title=task.title, status="todo", time=None, line_number=-1, indent="")
        _header = new_task.to_line() + '\n'
        _ranges = compute_field_ranges(_header) or (None, None, None, None)
        new_block = TaskBlock(task=new_task, header=_header, nodes=list(unfinished),
                              checkbox_range=_ranges[0], time_range=_ranges[1],
                              priority_range=_ranges[2], title_range=_ranges[3])
        from .weekly import append_block
        append_block(dst.nodes, new_block)
        dst._bump()
        return True

    def tab_task_block(self, task) -> bool:
        from .weekly import tab_task
        result = tab_task(self.nodes, task)
        if result:
            self._bump()
        return result

    def shift_tab_task_block(self, task) -> bool:
        from .weekly import shift_tab_task
        result = shift_tab_task(self.nodes, task)
        if result:
            self._bump()
        return result

    def reorder_block(self, task, direction: int) -> bool:
        from .weekly import move_block_in_nodes
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
        if key not in self._days:
            files = FileFinder.find_journal_files(
                self.directory, date_from=day, date_to=day
            )
            self._load_into_state(key, files[0] if files else None)
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
        return key, self._days[key]

    def reload_day_by_key(self, key: str, new_file_path: str | None = None) -> None:
        existing = self._days.get(key)
        fp = new_file_path if new_file_path is not None else (
            existing.file_path if existing else None
        )
        self._load_into_state(key, fp)

    def _load_into_state(self, key: str, file_path: str | None) -> None:
        if file_path and os.path.exists(file_path):
            nodes = parse(file_path)
        else:
            nodes = []
        self._days[key] = DayCache(file_path=file_path, nodes=nodes)


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
