import subprocess
from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import Static


class BlackboardWidget(VerticalScroll, can_focus=True):
    DEFAULT_CSS = """
    BlackboardWidget {
        width: 1fr;
        height: 10;
        border: solid $primary;
        padding: 0 1;
    }
    BlackboardWidget:focus {
        border: solid $warning;
    }
    """

    BINDINGS = [
        Binding("enter", "open_in_editor", "Edit", show=True),
    ]

    def __init__(self, desk_path: Path) -> None:
        super().__init__()
        self._desk_path = desk_path

    def _read(self) -> str:
        if not self._desk_path.exists():
            return "(no desk.md)"
        return self._desk_path.read_text()

    def compose(self) -> ComposeResult:
        yield Static(self._read(), id="blackboard-content")

    def reload(self) -> None:
        self.query_one("#blackboard-content", Static).update(self._read())


    def action_open_in_editor(self) -> None:
        with self.app.suspend():
            subprocess.run(["vim", str(self._desk_path)])
        self.reload()
