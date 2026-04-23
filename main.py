import datetime
import os
import re
import subprocess
import sys

from os_utils import FileFinder
from tools.journal_tools import TimelineTool, CatchUpTool


def _is_date(date_string: str) -> bool:
    return bool(re.fullmatch(r'\d{4}-\d{2}-\d{2}', date_string))


def _get_date(date_string: str) -> datetime.date:
    if date_string.lower() == 'today':
        return datetime.date.today()
    return datetime.datetime.strptime(date_string, "%Y-%m-%d").date()


def _open_journal_for_date(date_string: str, directory: str) -> None:
    date = _get_date(date_string)
    journal_files = FileFinder.find_journal_files(directory, date_from=date, date_to=date)
    if journal_files:
        subprocess.run(['vim', journal_files[0]])
    else:
        print(f"No journal files for {date} found")


def main():
    args = sys.argv[1:]
    journal_dir = os.environ.get('JOURNAL_DIR', '.')

    if not args:
        print("Usage: main.py <command> [subcommand] [args...]")
        return

    top = args[0].lower()
    if top not in ('journal',):
        print(f"Unknown command: {top}")
        return

    if len(args) < 2:
        print(f"Usage: main.py {top} <timeline|catch-up|today|YYYY-MM-DD>")
        return

    sub = args[1].lower()
    subcommands = {
        'timeline': lambda a: TimelineTool.run(a, journal_dir),
        'catch-up': lambda a: CatchUpTool.run(a, journal_dir),
    }

    if sub in subcommands:
        subcommands[sub](args[2:])
    elif sub == 'today' or _is_date(sub):
        _open_journal_for_date(sub, journal_dir)
    else:
        print(f"Unknown subcommand: {sub}")


if __name__ == '__main__':
    main()
