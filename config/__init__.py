import os
import yaml

_DEFAULT_CONFIG = os.path.join(os.path.dirname(__file__), 'task_config.yaml')
_USER_CONFIG = 'task_config.yaml'

_cached_config = None


def get_task_config() -> dict:
    global _cached_config
    if _cached_config is not None:
        return _cached_config

    path = _USER_CONFIG if os.path.exists(_USER_CONFIG) else _DEFAULT_CONFIG

    with open(path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)

    if not data:
        raise ValueError(f"{path} is empty")

    _required = ('checkbox_pattern', 'time_pattern', 'status_chars')
    missing = [k for k in _required if k not in data]
    if missing:
        raise ValueError(f"task_config.yaml missing required keys: {missing}")

    _cached_config = data
    return _cached_config
