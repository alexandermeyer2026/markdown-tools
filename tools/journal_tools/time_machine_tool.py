import curses
import os
import re
import shutil
import sys
from datetime import datetime as dt

from os_utils import FileFinder, resolve_date


def _resolve_file(arg: str, journal_dir: str) -> str:
    """Resolve a file path, date alias, or YYYY-MM-DD string to an absolute path."""
    date = resolve_date(arg)
    if date is not None:
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
        timestamps = [_extract_ts(b) for b in backups]

        curses.wrapper(_browse, file_path, filename, backup_paths, timestamps, journal_dir)


# ── Helpers ───────────────────────────────────────────────────────────────────

_TS_RE = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?')


def _extract_ts(backup_name: str) -> str:
    m = _TS_RE.match(backup_name)
    return m.group() if m else backup_name


def _fmt_ts(ts: str) -> str:
    for fmt in ('%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S'):
        try:
            return dt.strptime(ts, fmt).strftime('%Y-%m-%d  %H:%M:%S')
        except ValueError:
            continue
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

    selected  = 0
    scroll    = 0
    diff_mode = False
    focus     = 'left'   # 'left' | 'right'
    LEFT_W    = max(22, len(f" Time Machine: {filename} "))

    current_lines = _read(file_path) if os.path.exists(file_path) else []

    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        right_x = LEFT_W + 1
        right_w = w - right_x
        content_h = h - 3  # rows between header and status bar

        # ── right panel: content or diff (computed early for header) ────────────
        selected_lines = _read(backup_paths[selected])
        if diff_mode:
            display = _diff(current_lines, selected_lines)
            panel_title = " diff vs current "
        else:
            display = [l.rstrip('\n') for l in selected_lines]
            panel_title = f" {_fmt_ts(timestamps[selected])} "

        # ── header ────────────────────────────────────────────────────────────
        left_header  = f" Time Machine: {filename} ".ljust(LEFT_W)[:LEFT_W]
        right_header = panel_title.ljust(right_w)[:right_w]
        left_attr  = (curses.color_pair(1) | curses.A_BOLD) if focus == 'left'  else curses.color_pair(1)
        right_attr = (curses.color_pair(1) | curses.A_BOLD) if focus == 'right' else curses.color_pair(1)
        try:
            stdscr.addstr(0, 0,       left_header,  left_attr)
            stdscr.addstr(0, LEFT_W,  '│',           curses.color_pair(1))
            stdscr.addstr(0, right_x, right_header,  right_attr)
        except curses.error:
            pass

        # ── left panel: version list ──────────────────────────────────────────
        for i, ts in enumerate(timestamps):
            row = 1 + i
            if row > content_h:
                break
            label = f" {_fmt_ts(ts)}"
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

        # ── right panel: content ─────────────────────────────────────────────
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
        if focus == 'left':
            hints = f"[j/k] version  [l] →content  {d_hint}  [r] restore  [q] quit  ({selected + 1}/{len(timestamps)})"
        else:
            hints = f"[h] →versions  [j/k] scroll  {d_hint}  [r] restore  [q] quit"
        try:
            stdscr.addstr(h - 2, 0, f"  {hints}".ljust(w)[:w], curses.color_pair(6))
        except curses.error:
            pass

        stdscr.refresh()

        # ── input ─────────────────────────────────────────────────────────────
        key = stdscr.getch()

        if key in (ord('q'), ord('Q'), 27):
            break
        elif key == ord('l') and focus == 'left':
            focus = 'right'
        elif key == ord('h') and focus == 'right':
            focus = 'left'
        elif key == ord('k'):
            if focus == 'left' and selected > 0:
                selected -= 1
                scroll = 0
            elif focus == 'right':
                scroll = max(0, scroll - 1)
        elif key == ord('j'):
            if focus == 'left' and selected < len(timestamps) - 1:
                selected += 1
                scroll = 0
            elif focus == 'right':
                scroll = min(scroll + 1, max(0, len(display) - content_h))
        elif key in (ord('d'), ord('D')):
            diff_mode = not diff_mode
            scroll = 0
        elif key in (ord('r'), ord('R')):
            prompt = f" Restore {_fmt_ts(timestamps[selected])}? [y/N] "
            try:
                stdscr.addstr(h - 1, 0, prompt.ljust(w)[:w], curses.color_pair(5) | curses.A_BOLD)
            except curses.error:
                pass
            stdscr.refresh()
            confirm = stdscr.getch()
            if confirm not in (ord('y'), ord('Y')):
                continue
            from os_utils.backup_manager import BackupManager
            if os.path.exists(file_path):
                BackupManager.backup(file_path, journal_dir)
            shutil.copy2(backup_paths[selected], file_path)
            current_lines = _read(file_path)
            # re-scan so the newly created backup appears in the list
            backup_dir = os.path.dirname(backup_paths[0])
            new_backups = sorted(
                [f for f in os.listdir(backup_dir) if f.endswith(f'_{filename}')],
                reverse=True,
            )
            backup_paths = [os.path.join(backup_dir, b) for b in new_backups]
            timestamps   = [_extract_ts(b) for b in new_backups]
            selected     = min(selected, len(timestamps) - 1)
            msg = f" Restored {_fmt_ts(timestamps[selected])} — press any key "
            try:
                stdscr.addstr(h - 1, 0, msg.ljust(w)[:w], curses.color_pair(3) | curses.A_BOLD)
            except curses.error:
                pass
            stdscr.refresh()
            stdscr.getch()
