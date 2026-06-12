import datetime
import os
import textwrap
from dataclasses import dataclass, field

from models import top_level_tasks
from os_utils import FileFinder
from parser import TaskParser


@dataclass
class DayCache:
    file_path: str | None
    all_tasks: list          # original flat parse (for cut operations)
    task_list: list          # current top-level tasks (mutable, shared with WeekState)
    original_task_list: list # snapshot at load time (for change detection)
    original_lines: dict     # {line_number: original to_line()} for status detection
    original_bodies: dict = field(default_factory=dict)   # {line_number: body} snapshot
    moved_subtasks: list = field(default_factory=list)    # subtasks removed from parents
    deleted_tasks: list = field(default_factory=list)     # root tasks deleted in this day


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
            all_tasks = TaskParser.parse_file(file_path)
        else:
            all_tasks = []
        for t in all_tasks:
            if t.body is not None:
                t.body = textwrap.dedent(t.body).strip() or None
        tl = list(top_level_tasks(all_tasks))
        self._days[key] = DayCache(
            file_path=file_path,
            all_tasks=all_tasks,
            task_list=tl,
            original_task_list=list(tl),
            original_lines={t.line_number: t.to_line() for t in all_tasks},
            original_bodies={
                t.line_number: t.body for t in all_tasks if t.line_number > 0
            },
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
