import datetime
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from tools.journal_tools.sync_tool import (
    _resolve_date,
    _cmd_push,
    _cmd_pull,
    _cmd_login,
    SyncTool,
)

FAKE_CONFIG = {'url': 'https://journal.example.com', 'token': 'fake-token'}


def _mock_response(status: int, body: bytes):
    return (status, body)


class TestResolveDate(unittest.TestCase):
    def test_today(self):
        self.assertEqual(_resolve_date('today'), datetime.date.today())

    def test_tomorrow(self):
        self.assertEqual(_resolve_date('tomorrow'), datetime.date.today() + datetime.timedelta(days=1))

    def test_yesterday(self):
        self.assertEqual(_resolve_date('yesterday'), datetime.date.today() - datetime.timedelta(days=1))

    def test_explicit_date(self):
        self.assertEqual(_resolve_date('2025-01-15'), datetime.date(2025, 1, 15))

    def test_invalid_date_exits(self):
        with self.assertRaises(SystemExit):
            _resolve_date('not-a-date')


class TestLogin(unittest.TestCase):
    def test_login_success_saves_config(self):
        token_response = json.dumps({'access_token': 'mytoken'}).encode()
        with patch('tools.journal_tools.sync_tool._request', return_value=(200, token_response)), \
             patch('tools.journal_tools.sync_tool._save_config') as mock_save, \
             patch('getpass.getpass', return_value='mypassword'):
            _cmd_login(['https://journal.example.com'])
            mock_save.assert_called_once_with({'url': 'https://journal.example.com', 'token': 'mytoken'})

    def test_login_adds_https_prefix(self):
        token_response = json.dumps({'access_token': 'mytoken'}).encode()
        with patch('tools.journal_tools.sync_tool._request', return_value=(200, token_response)) as mock_req, \
             patch('tools.journal_tools.sync_tool._save_config'), \
             patch('getpass.getpass', return_value='pw'):
            _cmd_login(['journal.example.com'])
            url_used = mock_req.call_args[0][1]
            self.assertTrue(url_used.startswith('https://'))

    def test_login_failed_exits(self):
        with patch('tools.journal_tools.sync_tool._request', return_value=(401, b'Unauthorized')), \
             patch('getpass.getpass', return_value='wrong'):
            with self.assertRaises(SystemExit):
                _cmd_login(['https://journal.example.com'])

    def test_login_no_args_exits(self):
        with self.assertRaises(SystemExit):
            _cmd_login([])


class TestPush(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.file = Path(self.tmp) / '2025-01-15.md'
        self.file.write_text('- [ ] Task A\n')

    def test_push_success(self, ):
        with patch('tools.journal_tools.sync_tool._request', return_value=(200, b'{}')), \
             patch('tools.journal_tools.sync_tool._load_config', return_value=FAKE_CONFIG):
            _cmd_push(['2025-01-15'], self.tmp)

    def test_push_sends_file_content(self):
        with patch('tools.journal_tools.sync_tool._request', return_value=(200, b'{}')) as mock_req, \
             patch('tools.journal_tools.sync_tool._load_config', return_value=FAKE_CONFIG):
            _cmd_push(['2025-01-15'], self.tmp)
            body = mock_req.call_args[1]['body']
            self.assertIn(b'- [ ] Task A', body)

    def test_push_file_not_found_exits(self):
        with patch('tools.journal_tools.sync_tool._load_config', return_value=FAKE_CONFIG):
            with self.assertRaises(SystemExit):
                _cmd_push(['2025-01-16'], self.tmp)

    def test_push_token_expired_exits(self):
        with patch('tools.journal_tools.sync_tool._request', return_value=(401, b'Unauthorized')), \
             patch('tools.journal_tools.sync_tool._load_config', return_value=FAKE_CONFIG):
            with self.assertRaises(SystemExit):
                _cmd_push(['2025-01-15'], self.tmp)

    def test_push_server_error_exits(self):
        with patch('tools.journal_tools.sync_tool._request', return_value=(500, b'error')), \
             patch('tools.journal_tools.sync_tool._load_config', return_value=FAKE_CONFIG):
            with self.assertRaises(SystemExit):
                _cmd_push(['2025-01-15'], self.tmp)

    def test_push_no_args_exits(self):
        with patch('tools.journal_tools.sync_tool._load_config', return_value=FAKE_CONFIG):
            with self.assertRaises(SystemExit):
                _cmd_push([], self.tmp)


class TestPull(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_pull_creates_file(self):
        content = b'- [ ] Task A\n'
        with patch('tools.journal_tools.sync_tool._request', return_value=(200, content)), \
             patch('tools.journal_tools.sync_tool._load_config', return_value=FAKE_CONFIG):
            _cmd_pull(['2025-01-15'], self.tmp)
            self.assertEqual((Path(self.tmp) / '2025-01-15.md').read_bytes(), content)

    def test_pull_overwrites_existing_file(self):
        existing = Path(self.tmp) / '2025-01-15.md'
        existing.write_text('old content\n')
        new_content = b'- [x] Task A\n'
        with patch('tools.journal_tools.sync_tool._request', return_value=(200, new_content)), \
             patch('tools.journal_tools.sync_tool._load_config', return_value=FAKE_CONFIG):
            _cmd_pull(['2025-01-15'], self.tmp)
            self.assertEqual(existing.read_bytes(), new_content)

    def test_pull_backs_up_existing_file(self):
        existing = Path(self.tmp) / '2025-01-15.md'
        existing.write_text('old content\n')
        with patch('tools.journal_tools.sync_tool._request', return_value=(200, b'new\n')), \
             patch('tools.journal_tools.sync_tool._load_config', return_value=FAKE_CONFIG):
            _cmd_pull(['2025-01-15'], self.tmp)
            backups = list((Path(self.tmp) / '.backups').glob('*.md'))
            self.assertEqual(len(backups), 1)

    def test_pull_no_backup_if_file_absent(self):
        with patch('tools.journal_tools.sync_tool._request', return_value=(200, b'new\n')), \
             patch('tools.journal_tools.sync_tool._load_config', return_value=FAKE_CONFIG):
            _cmd_pull(['2025-01-15'], self.tmp)
            self.assertFalse((Path(self.tmp) / '.backups').exists())

    def test_pull_not_found_exits(self):
        with patch('tools.journal_tools.sync_tool._request', return_value=(404, b'Not Found')), \
             patch('tools.journal_tools.sync_tool._load_config', return_value=FAKE_CONFIG):
            with self.assertRaises(SystemExit):
                _cmd_pull(['2025-01-15'], self.tmp)

    def test_pull_token_expired_exits(self):
        with patch('tools.journal_tools.sync_tool._request', return_value=(401, b'Unauthorized')), \
             patch('tools.journal_tools.sync_tool._load_config', return_value=FAKE_CONFIG):
            with self.assertRaises(SystemExit):
                _cmd_pull(['2025-01-15'], self.tmp)

    def test_pull_no_args_exits(self):
        with patch('tools.journal_tools.sync_tool._load_config', return_value=FAKE_CONFIG):
            with self.assertRaises(SystemExit):
                _cmd_pull([], self.tmp)


class TestSyncToolRun(unittest.TestCase):
    def test_unknown_subcommand(self):
        with patch('builtins.print') as mock_print:
            SyncTool.run(['unknown'], '.')
            mock_print.assert_called()

    def test_no_args_prints_usage(self):
        with patch('builtins.print') as mock_print:
            SyncTool.run([], '.')
            mock_print.assert_called()
