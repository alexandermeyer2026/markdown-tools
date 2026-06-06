import os
import re
import shutil
import sys
from datetime import datetime as dt

from rich.console import Group
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, HorizontalGroup
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, Label, Static

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

        TimeMachineApp(file_path, filename, backup_paths, timestamps, journal_dir).run()


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


# ── Textual TUI ───────────────────────────────────────────────────────────────

class RestoreDialog(ModalScreen[bool]):
    DEFAULT_CSS = """
    RestoreDialog {
        align: center middle;
    }
    RestoreDialog > HorizontalGroup {
        background: $surface;
        border: round $warning;
        padding: 1 2;
        width: auto;
        height: auto;
    }
    RestoreDialog Label {
        width: auto;
        margin-right: 2;
        content-align: left middle;
    }
    RestoreDialog Button {
        margin-left: 1;
    }
    """

    BINDINGS = [
        Binding("y",      "confirm", show=False),
        Binding("n",      "cancel",  show=False),
        Binding("escape", "cancel",  show=False),
    ]

    def __init__(self, ts_label: str) -> None:
        super().__init__()
        self._ts_label = ts_label

    def compose(self) -> ComposeResult:
        with HorizontalGroup():
            yield Label(f"Restore {self._ts_label}?")
            yield Button("Yes", id="yes", variant="warning")
            yield Button("No",  id="no",  variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class VersionList(Widget, can_focus=True):
    DEFAULT_CSS = """
    VersionList {
        width: 24;
        height: 1fr;
    }
    """

    BINDINGS = [
        Binding("j", "cursor_down", show=False),
        Binding("k", "cursor_up",   show=False),
        Binding("l", "focus_right", show=False),
        Binding("d", "toggle_diff", show=False),
        Binding("r", "restore",     show=False),
    ]

    selected: reactive[int] = reactive(0, repaint=True)

    def __init__(self, timestamps: list[str]) -> None:
        super().__init__()
        self._timestamps = timestamps

    def watch_selected(self, _value: int) -> None:
        self.app.refresh_content()  # type: ignore[attr-defined]

    def on_focus(self) -> None:
        self.app._update_hints()  # type: ignore[attr-defined]

    def render(self) -> Group:
        w = max(self.size.width, 1)
        lines: list[Text] = []
        for i, ts in enumerate(self._timestamps):
            label = f" {_fmt_ts(ts)}"
            t = Text(label.ljust(w)[:w])
            if i == self.selected:
                t.stylize("reverse")
            lines.append(t)
        return Group(*lines)

    def update_list(self, timestamps: list[str]) -> None:
        self._timestamps = timestamps
        self.selected = min(self.selected, len(timestamps) - 1)
        self.refresh()

    def action_cursor_down(self) -> None:
        if self.selected < len(self._timestamps) - 1:
            self.selected += 1

    def action_cursor_up(self) -> None:
        if self.selected > 0:
            self.selected -= 1

    def action_focus_right(self) -> None:
        self.app.query_one(ContentView).focus()

    def action_toggle_diff(self) -> None:
        self.app.toggle_diff()  # type: ignore[attr-defined]

    def action_restore(self) -> None:
        self.app.restore()  # type: ignore[attr-defined]


class ContentView(Widget, can_focus=True):
    DEFAULT_CSS = """
    ContentView {
        width: 1fr;
        height: 1fr;
        border-left: solid $primary;
    }
    """

    BINDINGS = [
        Binding("j", "scroll_down", show=False),
        Binding("k", "scroll_up",   show=False),
        Binding("h", "focus_left",  show=False),
        Binding("d", "toggle_diff", show=False),
        Binding("r", "restore",     show=False),
    ]

    scroll_offset: reactive[int] = reactive(0, repaint=True)

    def __init__(self) -> None:
        super().__init__()
        self._lines: list[str] = []
        self._diff_mode: bool = False

    def on_focus(self) -> None:
        self.app._update_hints()  # type: ignore[attr-defined]

    def set_lines(self, lines: list[str], diff_mode: bool) -> None:
        self._lines = lines
        self._diff_mode = diff_mode
        self.scroll_offset = 0
        self.refresh()

    def render(self) -> Group:
        h = max(self.size.height, 1)
        w = max(self.size.width, 1)
        visible = self._lines[self.scroll_offset: self.scroll_offset + h]
        result: list[Text] = []
        for line in visible:
            if self._diff_mode:
                if line.startswith('+') and not line.startswith('+++'):
                    t = Text(line[:w], style="green")
                elif line.startswith('-') and not line.startswith('---'):
                    t = Text(line[:w], style="red")
                elif line.startswith('@'):
                    t = Text(line[:w], style="yellow")
                else:
                    t = Text(line[:w])
            else:
                t = Text(line[:w])
            result.append(t)
        return Group(*result)

    def action_scroll_down(self) -> None:
        max_scroll = max(0, len(self._lines) - self.size.height)
        self.scroll_offset = min(self.scroll_offset + 1, max_scroll)

    def action_scroll_up(self) -> None:
        self.scroll_offset = max(0, self.scroll_offset - 1)

    def action_focus_left(self) -> None:
        self.app.query_one(VersionList).focus()

    def action_toggle_diff(self) -> None:
        self.app.toggle_diff()  # type: ignore[attr-defined]

    def action_restore(self) -> None:
        self.app.restore()  # type: ignore[attr-defined]


class TimeMachineApp(App):
    DEFAULT_CSS = """
    TimeMachineApp {
        layout: vertical;
    }
    #panels {
        height: 1fr;
    }
    #hints {
        height: 1;
        background: $primary;
        color: $background;
        padding: 0 2;
    }
    """

    BINDINGS = [
        Binding("q",      "quit", show=False),
        Binding("ctrl+c", "quit", show=False),
    ]

    def __init__(
        self,
        file_path: str,
        filename: str,
        backup_paths: list[str],
        timestamps: list[str],
        journal_dir: str,
    ) -> None:
        super().__init__()
        self._file_path     = file_path
        self._filename      = filename
        self._backup_paths  = backup_paths
        self._timestamps    = timestamps
        self._journal_dir   = journal_dir
        self._diff_mode     = False
        self._current_lines = _read(file_path) if os.path.exists(file_path) else []

    def compose(self) -> ComposeResult:
        with Horizontal(id="panels"):
            yield VersionList(self._timestamps)
            yield ContentView()
        yield Static("", id="hints")

    def on_mount(self) -> None:
        self.title = f"Time Machine: {self._filename}"
        self.query_one(VersionList).focus()
        self.refresh_content()

    def refresh_content(self) -> None:
        version_list = self.query_one(VersionList)
        content_view = self.query_one(ContentView)
        idx = version_list.selected
        selected_lines = _read(self._backup_paths[idx])
        if self._diff_mode:
            lines = _diff(self._current_lines, selected_lines)
        else:
            lines = [line.rstrip('\n') for line in selected_lines]
        content_view.set_lines(lines, self._diff_mode)
        self._update_hints()

    def _update_hints(self) -> None:
        focused = self.focused
        d_hint = "[d] content" if self._diff_mode else "[d] diff"
        idx = self.query_one(VersionList).selected
        n = len(self._timestamps)
        if isinstance(focused, ContentView):
            hints = f"[h] →versions  [j/k] scroll  {d_hint}  [r] restore  [q] quit"
        else:
            hints = f"[j/k] version  [l] →content  {d_hint}  [r] restore  [q] quit  ({idx + 1}/{n})"
        self.query_one("#hints", Static).update(f"  {hints}")

    def toggle_diff(self) -> None:
        self._diff_mode = not self._diff_mode
        self.refresh_content()

    def restore(self) -> None:
        idx = self.query_one(VersionList).selected
        ts_label = _fmt_ts(self._timestamps[idx])

        def on_confirmed(confirmed: bool) -> None:
            if not confirmed:
                return
            from os_utils.backup_manager import BackupManager
            if os.path.exists(self._file_path):
                BackupManager.backup(self._file_path, self._journal_dir)
            shutil.copy2(self._backup_paths[idx], self._file_path)
            self._current_lines = _read(self._file_path)
            backup_dir = os.path.dirname(self._backup_paths[0])
            new_backups = sorted(
                [f for f in os.listdir(backup_dir) if f.endswith(f'_{self._filename}')],
                reverse=True,
            )
            self._backup_paths = [os.path.join(backup_dir, b) for b in new_backups]
            self._timestamps   = [_extract_ts(b) for b in new_backups]
            self.query_one(VersionList).update_list(self._timestamps)
            self.refresh_content()
            self.notify(f"Restored {ts_label}", severity="information")

        self.push_screen(RestoreDialog(ts_label), on_confirmed)
