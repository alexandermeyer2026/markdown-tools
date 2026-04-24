from .task import Task, TaskTime, get_minutes, minutes_to_time


def top_level_tasks(tasks: list[Task]) -> list[Task]:
    return [t for t in tasks if t.parent is None]


__all__ = ['Task', 'TaskTime', 'get_minutes', 'minutes_to_time', 'top_level_tasks']
