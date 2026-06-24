import asyncio
import contextlib
import datetime
import os
import shutil
import tempfile
from unittest.mock import MagicMock, patch

import pytest

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), 'fixtures')
INPUT_DIR = os.path.join(FIXTURES_DIR, 'input')
EXPECTED_DIR = os.path.join(FIXTURES_DIR, 'expected')


@pytest.fixture
def run_planner_scenario():
    def _run(scenario_fn, fixture_name, week_today=None, date=None):
        asyncio.run(_execute(scenario_fn, fixture_name, week_today, date))

    async def _execute(scenario_fn, fixture_name, week_today, date):
        from os_utils import FileFinder
        from tools.journal_tools.planner.app import PlannerApp

        tmpdir = tempfile.mkdtemp()
        try:
            for fname in os.listdir(INPUT_DIR):
                shutil.copy(os.path.join(INPUT_DIR, fname), os.path.join(tmpdir, fname))

            patches = []
            if week_today:
                fixed = datetime.date.fromisoformat(week_today)
                mock_dt = MagicMock()
                mock_dt.date.today.return_value = fixed
                mock_dt.timedelta = datetime.timedelta
                mock_dt.date.fromisoformat = datetime.date.fromisoformat
                patches.append(
                    patch('tools.journal_tools.planner.week_screen.datetime', mock_dt)
                )

            file_path = None
            if date:
                d = datetime.date.fromisoformat(date)
                files = FileFinder.find_journal_files(tmpdir, date_from=d, date_to=d)
                file_path = files[0] if files else None

            with contextlib.ExitStack() as stack:
                for p in patches:
                    stack.enter_context(p)
                app = PlannerApp(tmpdir, file_path=file_path)
                async with app.run_test() as pilot:
                    await pilot.pause()
                    await scenario_fn(pilot, app)

            expected_dir = os.path.join(EXPECTED_DIR, 'planner', fixture_name)
            for fname in sorted(os.listdir(expected_dir)):
                expected_path = os.path.join(expected_dir, fname)
                actual_path = os.path.join(tmpdir, fname)
                with open(expected_path, encoding='utf-8') as f:
                    expected = f.read()
                with open(actual_path, encoding='utf-8') as f:
                    actual = f.read()
                assert actual == expected, (
                    f"Mismatch in {fname}:\n\n"
                    f"Expected:\n{expected!r}\n\n"
                    f"Actual:\n{actual!r}"
                )
        finally:
            shutil.rmtree(tmpdir)

    return _run
