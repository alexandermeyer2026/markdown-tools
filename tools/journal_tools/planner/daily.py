import os

from os_utils import BackupManager, FileWriter
from parser.file_model import serialize


def has_changes(day) -> bool:
    return serialize(day.nodes) != day.original_content


def save(day, directory):
    content = serialize(day.nodes)
    if content == day.original_content:
        return
    if day.file_path and os.path.exists(day.file_path):
        BackupManager.backup(day.file_path, directory)
    FileWriter.write_atomic(day.file_path, content.splitlines(keepends=True))
    day.original_content = content
