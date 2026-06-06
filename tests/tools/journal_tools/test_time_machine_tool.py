import asyncio
import os
import shutil
import tempfile
import unittest

from tools.journal_tools.time_machine_tool import (
    TimeMachineApp,
    RestoreDialog,
    VersionList,
    ContentView,
    _extract_ts,
    _fmt_ts,
    _diff,
    _read,
)


# ── Unit tests ────────────────────────────────────────────────────────────────

class TestExtractTs(unittest.TestCase):
    def test_extracts_datetime_with_microseconds(self):
        self.assertEqual(
            _extract_ts('2024-01-15T09:30:00.123456_notes.md'),
            '2024-01-15T09:30:00.123456',
        )

    def test_extracts_datetime_without_microseconds(self):
        self.assertEqual(
            _extract_ts('2024-01-15T09:30:00_notes.md'),
            '2024-01-15T09:30:00',
        )

    def test_no_match_returns_full_name(self):
        self.assertEqual(_extract_ts('notimestamp.md'), 'notimestamp.md')


class TestFmtTs(unittest.TestCase):
    def test_formats_with_microseconds(self):
        self.assertEqual(_fmt_ts('2024-01-15T09:30:00.123456'), '2024-01-15  09:30:00')

    def test_formats_without_microseconds(self):
        self.assertEqual(_fmt_ts('2024-01-15T09:30:00'), '2024-01-15  09:30:00')

    def test_unrecognised_string_returned_as_is(self):
        self.assertEqual(_fmt_ts('garbage'), 'garbage')


class TestRead(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            mode='w', suffix='.md', delete=False, encoding='utf-8'
        )
        self.tmp.write('line one\nline two\n')
        self.tmp.close()

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_reads_lines(self):
        self.assertEqual(_read(self.tmp.name), ['line one\n', 'line two\n'])

    def test_missing_file_returns_error_line(self):
        result = _read('/nonexistent/path.md')
        self.assertEqual(len(result), 1)
        self.assertIn('error', result[0])


class TestDiff(unittest.TestCase):
    def test_produces_unified_diff(self):
        current  = ['hello\n', 'world\n']
        selected = ['hello\n', 'earth\n']
        result   = _diff(current, selected)
        self.assertTrue(any('-world' in l for l in result))
        self.assertTrue(any('+earth' in l for l in result))

    def test_identical_files_produce_no_diff(self):
        lines = ['same\n', 'content\n']
        self.assertEqual(_diff(lines, lines), [])


# ── Pilot-driven tests ────────────────────────────────────────────────────────

def _make_app(current_content: str, backup_contents: list[str]) -> TimeMachineApp:
    """Build a TimeMachineApp with an in-memory-style temp tree."""
    tmp = tempfile.mkdtemp()
    file_path  = os.path.join(tmp, 'notes.md')
    backup_dir = os.path.join(tmp, '.backups')
    os.makedirs(backup_dir)

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(current_content)

    timestamps = [
        f'2024-01-1{i}T10:00:00' for i in range(len(backup_contents))
    ]
    backup_paths = []
    for ts, content in zip(timestamps, backup_contents):
        path = os.path.join(backup_dir, f'{ts}_notes.md')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        backup_paths.append(path)

    backup_paths = list(reversed(backup_paths))
    timestamps   = list(reversed(timestamps))

    return TimeMachineApp(
        file_path=file_path,
        filename='notes.md',
        backup_paths=backup_paths,
        timestamps=timestamps,
        journal_dir=tmp,
    ), tmp


class TestVersionListNavigation(unittest.TestCase):
    def setUp(self):
        self.app, self.tmp = _make_app(
            current_content='current\n',
            backup_contents=['v1\n', 'v2\n', 'v3\n'],
        )

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_initial_selection_is_zero(self):
        async def run():
            async with self.app.run_test() as pilot:
                await pilot.pause()
                return self.app.query_one(VersionList).selected
        self.assertEqual(asyncio.run(run()), 0)

    def test_j_moves_selection_down(self):
        async def run():
            async with self.app.run_test() as pilot:
                await pilot.pause()
                await pilot.press('j')
                return self.app.query_one(VersionList).selected
        self.assertEqual(asyncio.run(run()), 1)

    def test_k_moves_selection_up(self):
        async def run():
            async with self.app.run_test() as pilot:
                await pilot.pause()
                await pilot.press('j')
                await pilot.press('j')
                await pilot.press('k')
                return self.app.query_one(VersionList).selected
        self.assertEqual(asyncio.run(run()), 1)

    def test_k_clamps_at_top(self):
        async def run():
            async with self.app.run_test() as pilot:
                await pilot.pause()
                await pilot.press('k')
                return self.app.query_one(VersionList).selected
        self.assertEqual(asyncio.run(run()), 0)

    def test_j_clamps_at_bottom(self):
        async def run():
            async with self.app.run_test() as pilot:
                await pilot.pause()
                await pilot.press('j')
                await pilot.press('j')
                await pilot.press('j')
                await pilot.press('j')
                return self.app.query_one(VersionList).selected
        self.assertEqual(asyncio.run(run()), 2)


class TestFocusSwitch(unittest.TestCase):
    def setUp(self):
        self.app, self.tmp = _make_app('current\n', ['v1\n'])

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_l_moves_focus_to_content_view(self):
        async def run():
            async with self.app.run_test() as pilot:
                await pilot.pause()
                await pilot.press('l')
                return isinstance(self.app.focused, ContentView)
        self.assertTrue(asyncio.run(run()))

    def test_h_from_content_view_returns_focus_to_version_list(self):
        async def run():
            async with self.app.run_test() as pilot:
                await pilot.pause()
                await pilot.press('l')
                await pilot.press('h')
                return isinstance(self.app.focused, VersionList)
        self.assertTrue(asyncio.run(run()))


class TestDiffToggle(unittest.TestCase):
    def setUp(self):
        self.app, self.tmp = _make_app('current\n', ['old\n'])

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_d_enables_diff_mode(self):
        async def run():
            async with self.app.run_test() as pilot:
                await pilot.pause()
                await pilot.press('d')
                return self.app._diff_mode
        self.assertTrue(asyncio.run(run()))

    def test_d_twice_disables_diff_mode(self):
        async def run():
            async with self.app.run_test() as pilot:
                await pilot.pause()
                await pilot.press('d')
                await pilot.press('d')
                return self.app._diff_mode
        self.assertFalse(asyncio.run(run()))

    def test_d_from_content_view_also_toggles(self):
        async def run():
            async with self.app.run_test() as pilot:
                await pilot.pause()
                await pilot.press('l')
                await pilot.press('d')
                return self.app._diff_mode
        self.assertTrue(asyncio.run(run()))


class TestRestore(unittest.TestCase):
    def setUp(self):
        self.app, self.tmp = _make_app(
            current_content='current\n',
            backup_contents=['old version\n', 'older version\n'],
        )
        self.file_path = self.app._file_path

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_r_opens_restore_dialog(self):
        async def run():
            async with self.app.run_test() as pilot:
                await pilot.pause()
                await pilot.press('r')
                await pilot.pause()
                return isinstance(self.app.screen, RestoreDialog)
        self.assertTrue(asyncio.run(run()))

    def test_confirm_restore_replaces_file_content(self):
        async def run():
            async with self.app.run_test() as pilot:
                await pilot.pause()
                await pilot.press('r')
                await pilot.pause()
                await pilot.click('#yes')
                await pilot.pause()
        asyncio.run(run())
        with open(self.file_path, encoding='utf-8') as f:
            self.assertEqual(f.read(), 'older version\n')

    def test_cancel_restore_leaves_file_unchanged(self):
        async def run():
            async with self.app.run_test() as pilot:
                await pilot.pause()
                await pilot.press('r')
                await pilot.pause()
                await pilot.click('#no')
                await pilot.pause()
        asyncio.run(run())
        with open(self.file_path, encoding='utf-8') as f:
            self.assertEqual(f.read(), 'current\n')

    def test_n_key_cancels_restore(self):
        async def run():
            async with self.app.run_test() as pilot:
                await pilot.pause()
                await pilot.press('r')
                await pilot.pause()
                await pilot.press('n')
                await pilot.pause()
        asyncio.run(run())
        with open(self.file_path, encoding='utf-8') as f:
            self.assertEqual(f.read(), 'current\n')

    def test_restore_adds_new_backup_entry(self):
        async def run():
            async with self.app.run_test() as pilot:
                await pilot.pause()
                await pilot.press('r')
                await pilot.pause()
                await pilot.click('#yes')
                await pilot.pause()
                return len(self.app._backup_paths)
        count = asyncio.run(run())
        self.assertEqual(count, 3)

    def test_escape_cancels_restore_dialog(self):
        async def run():
            async with self.app.run_test() as pilot:
                await pilot.pause()
                await pilot.press('r')
                await pilot.pause()
                await pilot.press('escape')
                await pilot.pause()
                return isinstance(self.app.screen, RestoreDialog)
        self.assertFalse(asyncio.run(run()))


class TestQuit(unittest.TestCase):
    def setUp(self):
        self.app, self.tmp = _make_app('current\n', ['v1\n'])

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_q_exits_app(self):
        async def run():
            async with self.app.run_test() as pilot:
                await pilot.pause()
                await pilot.press('q')
        asyncio.run(run())  # should complete without hanging
