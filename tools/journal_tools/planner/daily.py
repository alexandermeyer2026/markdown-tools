import os

from os_utils import BackupManager, FileWriter


def has_changes(day) -> bool:
    return day.has_changes


def save(day, directory):
    if not day.has_changes:
        return
    if day.file_path is None:
        raise ValueError("cannot save a day with no file path")
    if os.path.exists(day.file_path):
        BackupManager.backup(day.file_path, directory)
    FileWriter.write_nodes(day.file_path, day.nodes)
    day._saved_version = day._version
