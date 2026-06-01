from dataclasses import dataclass, field


@dataclass
class DayCache:
    file_path: str | None
    all_tasks: list          # original flat parse (for cut operations)
    task_list: list          # current top-level tasks (mutable, shared with WeekState)
    original_task_list: list # snapshot at load time (for change detection)
    original_lines: dict     # {line_number: original to_line()} for status detection
    moved_subtasks: list = field(default_factory=list)  # subtasks removed from parents in this day


@dataclass
class WeekState:
    week_days: list
    directory: str
    cache: dict              # date ISO string -> DayCache

    def day(self, col: int) -> 'DayCache':
        return self.cache[self.week_days[col].isoformat()]
