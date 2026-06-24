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
)


def _make_app(current_content: str, backup_contents: list[str]):
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


def _run(app, coro):
    """Start app, pause for mount, run coro(pilot), return its result."""
    async def execute():
        async with app.run_test() as pilot:
            await pilot.pause()
            return await coro(pilot)
    return asyncio.run(execute())


class TestVersionListNavigation(unittest.TestCase):
    def test_navigation(self):
        # 3 backups + "Current" = 4 items (indices 0–3)
        cases = [
            ('initial selection',  [],             0),
            ('j moves down',       ['j'],          1),
            ('k moves up',         ['j', 'j', 'k'], 1),
            ('k clamps at top',    ['k'],           0),
            ('j clamps at bottom', ['j'] * 4,      3),
        ]
        for name, keys, expected in cases:
            with self.subTest(name):
                app, tmp = _make_app('current\n', ['v1\n', 'v2\n', 'v3\n'])
                try:
                    async def run(pilot, ks=keys, a=app):
                        for k in ks:
                            await pilot.press(k)
                        return a.query_one(VersionList).selected
                    self.assertEqual(_run(app, run), expected)
                finally:
                    shutil.rmtree(tmp)


class TestFocusSwitch(unittest.TestCase):
    def test_focus_navigation(self):
        cases = [
            ('l moves focus to ContentView',          ['l'],      ContentView),
            ('h from ContentView returns VersionList', ['l', 'h'], VersionList),
        ]
        for name, keys, widget_type in cases:
            with self.subTest(name):
                app, tmp = _make_app('current\n', ['v1\n'])
                try:
                    async def run(pilot, ks=keys, a=app, wt=widget_type):
                        for k in ks:
                            await pilot.press(k)
                        return isinstance(a.focused, wt)
                    self.assertTrue(_run(app, run))
                finally:
                    shutil.rmtree(tmp)


class TestDiffToggle(unittest.TestCase):
    def test_diff_mode(self):
        cases = [
            ('d enables diff mode',              ['d'],       True),
            ('d twice disables diff mode',       ['d', 'd'],  False),
            ('d from ContentView also toggles',  ['l', 'd'],  True),
        ]
        for name, keys, expected in cases:
            with self.subTest(name):
                app, tmp = _make_app('current\n', ['old\n'])
                try:
                    async def run(pilot, ks=keys, a=app):
                        for k in ks:
                            await pilot.press(k)
                        return a._diff_mode
                    self.assertEqual(_run(app, run), expected)
                finally:
                    shutil.rmtree(tmp)


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
        async def run(pilot):
            await pilot.press('j')
            await pilot.press('r')
            await pilot.pause()
            return isinstance(self.app.screen, RestoreDialog)
        self.assertTrue(_run(self.app, run))

    def test_r_on_current_does_not_open_dialog(self):
        async def run(pilot):
            await pilot.press('r')
            await pilot.pause()
            return isinstance(self.app.screen, RestoreDialog)
        self.assertFalse(_run(self.app, run))

    def test_confirm_restore_replaces_file_content(self):
        async def run(pilot):
            await pilot.press('j')
            await pilot.press('r')
            await pilot.pause()
            await pilot.click('#yes')
            await pilot.pause()
        _run(self.app, run)
        with open(self.file_path, encoding='utf-8') as f:
            self.assertEqual(f.read(), 'older version\n')

    def test_cancel_restore_leaves_file_unchanged(self):
        async def run(pilot):
            await pilot.press('j')
            await pilot.press('r')
            await pilot.pause()
            await pilot.click('#no')
            await pilot.pause()
        _run(self.app, run)
        with open(self.file_path, encoding='utf-8') as f:
            self.assertEqual(f.read(), 'current\n')

    def test_n_key_cancels_restore(self):
        async def run(pilot):
            await pilot.press('j')
            await pilot.press('r')
            await pilot.pause()
            await pilot.press('n')
            await pilot.pause()
        _run(self.app, run)
        with open(self.file_path, encoding='utf-8') as f:
            self.assertEqual(f.read(), 'current\n')

    def test_restore_adds_new_backup_entry(self):
        async def run(pilot):
            await pilot.press('j')
            await pilot.press('r')
            await pilot.pause()
            await pilot.click('#yes')
            await pilot.pause()
            return len(self.app._backup_paths)
        self.assertEqual(_run(self.app, run), 3)

    def test_escape_cancels_restore_dialog(self):
        async def run(pilot):
            await pilot.press('j')
            await pilot.press('r')
            await pilot.pause()
            await pilot.press('escape')
            await pilot.pause()
            return isinstance(self.app.screen, RestoreDialog)
        self.assertFalse(_run(self.app, run))


class TestQuit(unittest.TestCase):
    def setUp(self):
        self.app, self.tmp = _make_app('current\n', ['v1\n'])

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_q_exits_app(self):
        async def run(pilot):
            await pilot.press('q')
        _run(self.app, run)  # should complete without hanging
