from dataclasses import dataclass, field


@dataclass
class DayCache:
    file_path: str | None
    all_tasks: list          # original flat parse (for cut operations)
    task_list: list          # current top-level tasks (mutable, shared with WeekState)
    original_task_list: list # snapshot at load time (for change detection)
    original_lines: dict     # {line_number: original to_line()} for status detection
    new_tasks: list = field(default_factory=list)       # tasks created in-session (no line number)
    moved_subtasks: list = field(default_factory=list)  # subtasks removed from parents in this day


@dataclass
class WeekState:
    week_days: list
    week_tasks: list         # list references into cache DayCache.task_list
    file_paths: list
    all_tasks_per_day: list
    directory: str
    cache: dict              # date ISO string -> DayCache
