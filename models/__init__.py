from .task import Task, TaskTime, get_minutes, minutes_to_time, status_char_map


def top_level_tasks(tasks: list[Task]) -> list[Task]:
    return [t for t in tasks if t.parent is None]


__all__ = ['Task', 'TaskTime', 'get_minutes', 'minutes_to_time', 'status_char_map', 'top_level_tasks']
