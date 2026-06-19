import os

from os_utils import BackupManager, FileWriter
from parser.file_model import serialize


def has_changes(day) -> bool:
    return day.has_changes


def save(day, directory):
    if not day.has_changes:
        return
    if day.file_path is None:
        raise ValueError("cannot save a day with no file path")
    content = serialize(day.nodes)
    if os.path.exists(day.file_path):
        BackupManager.backup(day.file_path, directory)
    FileWriter.write_atomic(day.file_path, content.splitlines(keepends=True))
    day._saved_version = day._version
