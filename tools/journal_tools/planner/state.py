import datetime
import os
from dataclasses import dataclass

from os_utils import FileFinder
from parser.file_model import TaskBlock, parse, populate_task_relations, serialize


def _find_block_in(nodes: list, task) -> 'TaskBlock | None':
    for node in nodes:
        if isinstance(node, TaskBlock):
            if node.task is task:
                return node
            result = _find_block_in(node.nodes, task)
            if result is not None:
                return result
    return None


@dataclass
class DayCache:
    file_path: str | None
    nodes: list           # list[Node] — top-level node list (mutable)
    original_content: str # serialized file content at load time
    task_list: list       # [block.task for top-level TaskBlocks] — mutable by screens

    def find_block(self, task) -> 'TaskBlock | None':
        return _find_block_in(self.nodes, task)


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
            with open(file_path, 'r', encoding='utf-8') as f:
                original_content = f.read()
        else:
            nodes = []
            original_content = ''
        populate_task_relations(nodes)
        self._days[key] = DayCache(
            file_path=file_path,
            nodes=nodes,
            original_content=original_content,
            task_list=[n.task for n in nodes if isinstance(n, TaskBlock)],
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
