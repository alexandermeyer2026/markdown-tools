from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Button, Label
from textual.containers import Horizontal


class SaveDialog(ModalScreen[bool]):
    DEFAULT_CSS = """
    SaveDialog {
        align: center middle;
    }
    SaveDialog > Horizontal {
        background: $surface;
        border: round $primary;
        padding: 1 2;
        width: auto;
        height: auto;
    }
    SaveDialog Label {
        width: auto;
        margin-right: 2;
        content-align: left middle;
    }
    SaveDialog Button {
        margin-left: 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Label("Save changes?")
            yield Button("Yes", id="yes", variant="primary")
            yield Button("No", id="no", variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")
