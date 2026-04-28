import os
import shutil
from datetime import datetime


class BackupManager:
    BACKUP_DIR = '.backups'
    MAX_BACKUPS_PER_FILE = 10

    @staticmethod
    def backup(file_path: str, working_dir: str) -> None:
        backup_dir = os.path.join(working_dir, BackupManager.BACKUP_DIR)
        os.makedirs(backup_dir, exist_ok=True)

        timestamp = datetime.now().strftime('%Y-%m-%dT%H:%M:%S.%f')
        filename = os.path.basename(file_path)
        backup_path = os.path.join(backup_dir, f'{timestamp}_{filename}')
        shutil.copy2(file_path, backup_path)

        BackupManager._prune(backup_dir, filename)

    @staticmethod
    def _prune(backup_dir: str, filename: str) -> None:
        backups = sorted([
            f for f in os.listdir(backup_dir)
            if f.endswith(f'_{filename}')
        ])
        for old in backups[:-BackupManager.MAX_BACKUPS_PER_FILE]:
            os.remove(os.path.join(backup_dir, old))
