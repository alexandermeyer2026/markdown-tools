from dataclasses import dataclass

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalGroup, HorizontalGroup
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, TextArea

from models import Task


@dataclass
class TaskFormResult:
    title: str
    status: str
    time_start: str | None
    time_end: str | None
    body: str | None


_STATUS_OPTIONS: list[tuple[str, str]] = [
    ("○  Todo",        "todo"),
    ("◐  In progress", "in progress"),
    ("✓  Done",        "done"),
    ("✗  Failed",      "failed"),
]


class TaskFormScreen(ModalScreen[TaskFormResult | None]):
    BINDINGS = [
        Binding("ctrl+s", "save", "Save", show=True),
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    DEFAULT_CSS = """
    TaskFormScreen {
        align: center middle;
    }
    TaskFormScreen > VerticalGroup {
        background: $surface;
        border: round $primary;
        padding: 1 2;
        width: 60;
    }
    TaskFormScreen Label {
        margin-top: 1;
        color: $text-muted;
    }
    TaskFormScreen Input, TaskFormScreen Select {
        margin-bottom: 0;
    }
    TaskFormScreen TextArea {
        height: 5;
        margin-bottom: 0;
    }
    TaskFormScreen #buttons {
        margin-top: 1;
        align-horizontal: right;
    }
    TaskFormScreen Button {
        margin-left: 1;
    }
    """

    def __init__(self, task: Task | None = None):
        super().__init__()
        self._source_task = task

    def compose(self) -> ComposeResult:
        task = self._source_task
        with VerticalGroup():
            yield Label("Title")
            yield Input(
                value=task.title if task else "",
                placeholder="Task title",
                id="title",
            )
            yield Label("Status")
            yield Select(
                _STATUS_OPTIONS,
                value=task.status if task else "todo",
                id="status",
            )
            yield Label("Time start  (HH:MM, optional)")
            yield Input(
                value=task.time.start if task and task.time else "",
                placeholder="e.g. 09:00",
                id="time_start",
            )
            yield Label("Time end  (HH:MM, optional)")
            yield Input(
                value=task.time.end if task and task.time and task.time.end else "",
                placeholder="e.g. 10:00",
                id="time_end",
            )
            yield Label("Notes")
            yield TextArea(
                text=task.body if task and task.body else "",
                id="body",
            )
            with HorizontalGroup(id="buttons"):
                yield Button("Save", id="save", variant="primary")
                yield Button("Cancel", id="cancel", variant="default")

    def on_mount(self) -> None:
        self.query_one("#title", Input).focus()

    def action_save(self) -> None:
        title = self.query_one("#title", Input).value.strip()
        if not title:
            return
        status = self.query_one("#status", Select).value
        if not isinstance(status, str):
            status = "todo"
        time_start = self.query_one("#time_start", Input).value.strip() or None
        time_end = self.query_one("#time_end", Input).value.strip() or None
        body = self.query_one("#body", TextArea).text.strip() or None
        self.dismiss(TaskFormResult(
            title=title,
            status=status,
            time_start=time_start,
            time_end=time_end,
            body=body,
        ))

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self.action_save()
        else:
            self.action_cancel()
