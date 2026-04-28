import os
import tempfile
import unittest

from os_utils.backup_manager import BackupManager


class TestBackup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.file_path = os.path.join(self.tmp, '2025-01-15.md')
        with open(self.file_path, 'w') as f:
            f.write('- [ ] Task A\n')

    def _backups(self) -> list[str]:
        backup_dir = os.path.join(self.tmp, BackupManager.BACKUP_DIR)
        if not os.path.exists(backup_dir):
            return []
        return sorted(os.listdir(backup_dir))

    def test_backup_creates_file(self):
        BackupManager.backup(self.file_path, self.tmp)
        self.assertEqual(len(self._backups()), 1)

    def test_backup_filename_contains_original(self):
        BackupManager.backup(self.file_path, self.tmp)
        self.assertTrue(self._backups()[0].endswith('2025-01-15.md'))

    def test_backup_preserves_content(self):
        BackupManager.backup(self.file_path, self.tmp)
        backup_dir = os.path.join(self.tmp, BackupManager.BACKUP_DIR)
        backup_file = os.path.join(backup_dir, self._backups()[0])
        with open(backup_file) as f:
            self.assertEqual(f.read(), '- [ ] Task A\n')

    def test_backup_creates_backup_dir(self):
        backup_dir = os.path.join(self.tmp, BackupManager.BACKUP_DIR)
        self.assertFalse(os.path.exists(backup_dir))
        BackupManager.backup(self.file_path, self.tmp)
        self.assertTrue(os.path.exists(backup_dir))


class TestPrune(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.file_path = os.path.join(self.tmp, '2025-01-15.md')
        with open(self.file_path, 'w') as f:
            f.write('content')

    def _backup_count(self) -> int:
        backup_dir = os.path.join(self.tmp, BackupManager.BACKUP_DIR)
        return len([f for f in os.listdir(backup_dir) if f.endswith('2025-01-15.md')])

    def test_prune_keeps_max_backups(self):
        for _ in range(BackupManager.MAX_BACKUPS_PER_FILE + 2):
            BackupManager.backup(self.file_path, self.tmp)
        self.assertEqual(self._backup_count(), BackupManager.MAX_BACKUPS_PER_FILE)

    def test_prune_keeps_most_recent(self):
        for i in range(BackupManager.MAX_BACKUPS_PER_FILE + 1):
            with open(self.file_path, 'w') as f:
                f.write(f'version {i}')
            BackupManager.backup(self.file_path, self.tmp)

        backup_dir = os.path.join(self.tmp, BackupManager.BACKUP_DIR)
        backups = sorted(os.listdir(backup_dir))
        newest = os.path.join(backup_dir, backups[-1])
        with open(newest) as f:
            self.assertEqual(f.read(), f'version {BackupManager.MAX_BACKUPS_PER_FILE}')

    def test_prune_only_affects_same_filename(self):
        other_path = os.path.join(self.tmp, '2025-01-16.md')
        with open(other_path, 'w') as f:
            f.write('other')

        for _ in range(BackupManager.MAX_BACKUPS_PER_FILE + 2):
            BackupManager.backup(self.file_path, self.tmp)
        BackupManager.backup(other_path, self.tmp)

        backup_dir = os.path.join(self.tmp, BackupManager.BACKUP_DIR)
        other_backups = [f for f in os.listdir(backup_dir) if f.endswith('2025-01-16.md')]
        self.assertEqual(len(other_backups), 1)
