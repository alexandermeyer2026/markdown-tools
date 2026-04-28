import curses
import datetime
import os
import re
import shutil
import sys
from datetime import datetime as dt

from os_utils import FileFinder

_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
_DATE_ALIASES = {'today', 'yesterday', 'tomorrow'}


def _resolve_file(arg: str, journal_dir: str) -> str:
    """Resolve a file path, date alias, or YYYY-MM-DD string to an absolute path."""
    lowered = arg.lower()
    if lowered in _DATE_ALIASES or _DATE_RE.match(arg):
        today = datetime.date.today()
        match lowered:
            case 'today':     date = today
            case 'yesterday': date = today - datetime.timedelta(days=1)
            case 'tomorrow':  date = today + datetime.timedelta(days=1)
            case _:           date = datetime.datetime.strptime(arg, '%Y-%m-%d').date()
        files = FileFinder.find_journal_files(journal_dir, date_from=date, date_to=date)
        if not files:
            print(f"No journal file found for {date}")
            sys.exit(1)
        return files[0]
    return arg if os.path.isabs(arg) else os.path.join(journal_dir, arg)


class TimeMachineTool:
    @staticmethod
    def run(args: list[str], journal_dir: str) -> None:
        if not args:
            print("Usage: journal time-machine <file|date>")
            sys.exit(1)

        file_path = _resolve_file(args[0], journal_dir)
        filename = os.path.basename(file_path)
        backup_dir = os.path.join(journal_dir, '.backups')

        if not os.path.isdir(backup_dir):
            print(f"No backups found for {filename}")
            sys.exit(1)

        backups = sorted(
            [f for f in os.listdir(backup_dir) if f.endswith(f'_{filename}')],
            reverse=True,
        )

        if not backups:
            print(f"No backups found for {filename}")
            sys.exit(1)

        backup_paths = [os.path.join(backup_dir, b) for b in backups]
        timestamps = [b[:26] for b in backups]  # 'YYYY-MM-DDTHH:MM:SS.ffffff'

        curses.wrapper(_browse, file_path, filename, backup_paths, timestamps, journal_dir)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt_ts(ts: str) -> str:
    try:
        return dt.strptime(ts, '%Y-%m-%dT%H:%M:%S.%f').strftime('%Y-%m-%d  %H:%M:%S')
    except ValueError:
        return ts


def _read(path: str) -> list[str]:
    try:
        with open(path, encoding='utf-8') as f:
            return f.readlines()
    except Exception as e:
        return [f"(error: {e})\n"]


def _diff(current: list[str], selected: list[str]) -> list[str]:
    import difflib
    return list(difflib.unified_diff(
        current, selected,
        fromfile='current',
        tofile='this version',
        lineterm='',
    ))


# ── TUI ───────────────────────────────────────────────────────────────────────

def _browse(stdscr, file_path, filename, backup_paths, timestamps, journal_dir):
    curses.curs_set(0)
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_CYAN,  -1)                          # header
    curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_WHITE)          # selected row
    curses.init_pair(3, curses.COLOR_GREEN, -1)                          # diff add / confirm
    curses.init_pair(4, curses.COLOR_RED,   -1)                          # diff remove
    curses.init_pair(5, curses.COLOR_YELLOW, -1)                         # diff hunk
    curses.init_pair(6, curses.COLOR_BLACK, curses.COLOR_CYAN)           # status bar

    selected   = 0
    scroll     = 0
    diff_mode  = False
    LEFT_W     = 22

    current_lines = _read(file_path) if os.path.exists(file_path) else []

    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        right_x = LEFT_W + 1
        right_w = w - right_x
        content_h = h - 3  # rows between header and status bar

        # ── header ────────────────────────────────────────────────────────────
        header = f" Time Machine: {filename} "
        try:
            stdscr.addstr(0, 0, header.ljust(w)[:w], curses.color_pair(1) | curses.A_BOLD)
        except curses.error:
            pass

        # ── left panel: version list ──────────────────────────────────────────
        for i, ts in enumerate(timestamps):
            row = 1 + i
            if row > content_h:
                break
            label = f" {_fmt_ts(ts)[:16]}"
            attr  = curses.color_pair(2) if i == selected else 0
            try:
                stdscr.addstr(row, 0, label.ljust(LEFT_W)[:LEFT_W], attr)
            except curses.error:
                pass

        # ── divider ───────────────────────────────────────────────────────────
        for row in range(1, h - 2):
            try:
                stdscr.addch(row, LEFT_W, '│')
            except curses.error:
                pass

        # ── right panel: content or diff ──────────────────────────────────────
        selected_lines = _read(backup_paths[selected])
        if diff_mode:
            display = _diff(current_lines, selected_lines)
            panel_title = f" diff vs current "
        else:
            display = [l.rstrip('\n') for l in selected_lines]
            panel_title = f" {_fmt_ts(timestamps[selected])} "

        try:
            stdscr.addstr(0, right_x, panel_title[:right_w], curses.color_pair(1) | curses.A_BOLD)
        except curses.error:
            pass

        for i, line in enumerate(display[scroll: scroll + content_h]):
            row = 1 + i
            if diff_mode:
                if   line.startswith('+') and not line.startswith('+++'):
                    attr = curses.color_pair(3)
                elif line.startswith('-') and not line.startswith('---'):
                    attr = curses.color_pair(4)
                elif line.startswith('@'):
                    attr = curses.color_pair(5)
                else:
                    attr = 0
            else:
                attr = 0
            try:
                stdscr.addstr(row, right_x, line[:right_w - 1], attr)
            except curses.error:
                pass

        # ── status bar ────────────────────────────────────────────────────────
        d_hint = "[d] content" if diff_mode else "[d] diff"
        status = f"  [j/k] navigate  {d_hint}  [r] restore  [q] quit  ({selected + 1}/{len(timestamps)})"
        try:
            stdscr.addstr(h - 2, 0, status.ljust(w)[:w], curses.color_pair(6))
        except curses.error:
            pass

        stdscr.refresh()

        # ── input ─────────────────────────────────────────────────────────────
        key = stdscr.getch()

        if key in (ord('q'), ord('Q'), 27):
            break
        elif key == ord('k') and selected > 0:
            selected -= 1
            scroll = 0
        elif key == ord('j') and selected < len(timestamps) - 1:
            selected += 1
            scroll = 0
        elif key in (ord('d'), ord('D')):
            diff_mode = not diff_mode
            scroll = 0
        elif key in (curses.KEY_NPAGE, ord(' ')):
            scroll = min(scroll + content_h - 1, max(0, len(display) - 1))
        elif key == curses.KEY_PPAGE:
            scroll = max(0, scroll - (content_h - 1))
        elif key in (ord('r'), ord('R')):
            from os_utils.backup_manager import BackupManager
            if os.path.exists(file_path):
                BackupManager.backup(file_path, journal_dir)
            shutil.copy2(backup_paths[selected], file_path)
            current_lines = _read(file_path)
            msg = f" Restored {_fmt_ts(timestamps[selected])} — press any key "
            try:
                stdscr.addstr(h - 1, 0, msg.ljust(w)[:w], curses.color_pair(3) | curses.A_BOLD)
            except curses.error:
                pass
            stdscr.refresh()
            stdscr.getch()
