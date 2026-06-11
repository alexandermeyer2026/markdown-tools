import textwrap
from dataclasses import dataclass, field

from rich.console import Group
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalGroup, HorizontalGroup
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, Input, Label, Select, TextArea

from config import get_indent_step
from models import Task, TaskTime
from tools.journal_tools.rendering import STATUS_ICONS
from .utils import fix_parent_refs, flatten_tasks


@dataclass
class TaskFormResult:
    title: str
    status: str
    time_start: str | None
    time_end: str | None
    body: str | None
    subtasks: list[Task] = field(default_factory=list)


_STATUS_OPTIONS: list[tuple[str, str]] = [
    ("○  Todo",        "todo"),
    ("◐  In progress", "in progress"),
    ("~  Started",     "started"),
    ("✓  Done",        "done"),
    ("✗  Failed",      "failed"),
]


class SubtaskList(Widget, can_focus=True):
    BINDINGS = [
        Binding("j",     "cursor_down",    show=False),
        Binding("k",     "cursor_up",      show=False),
        Binding("n",     "add_subtask",    show=False),
        Binding("enter", "edit_subtask",   show=False),
        Binding("D",     "delete_subtask", show=False),
    ]

    cursor_idx: reactive[int] = reactive(0, repaint=True)

    def __init__(self, task: Task | None, children: list[Task]) -> None:
        super().__init__()
        self._source_task = task
        self._children = children

    def _flat(self) -> list[Task]:
        return flatten_tasks(self._children)

    def get_content_height(self, container_size, viewport_size, width: int) -> int:
        return max(len(self._flat()), 1)

    def render(self) -> Group | Text:
        flat = self._flat()
        if not flat:
            return Text("  press n to add", style="dim")
        cursor_task = flat[min(self.cursor_idx, len(flat) - 1)]
        lines = self._render_children(self._children, depth=0, cursor_task=cursor_task)
        return Group(*lines)

    def _render_children(
        self, tasks: list[Task], depth: int, cursor_task: Task | None
    ) -> list[Text]:
        lines = []
        for task in tasks:
            icon = STATUS_ICONS.get(task.status, "?")
            indent = "  " * depth
            is_sel = task is cursor_task and self.has_focus
            t = Text(indent + icon + " " + task.title)
            if is_sel:
                t.stylize("reverse")
            lines.append(t)
            lines.extend(self._render_children(task.children, depth + 1, cursor_task))
        return lines

    def action_cursor_down(self) -> None:
        flat = self._flat()
        if flat:
            self.cursor_idx = min(self.cursor_idx + 1, len(flat) - 1)

    def action_cursor_up(self) -> None:
        if self.cursor_idx > 0:
            self.cursor_idx -= 1

    def action_add_subtask(self) -> None:
        def on_result(result: TaskFormResult | None) -> None:
            if result is None:
                return
            time = None
            if result.time_start:
                time = TaskTime(
                    start=result.time_start,
                    end=result.time_end if result.time_end else None,
                )
            parent_indent = self._source_task.indent if self._source_task else ""
            new_task = Task(
                title=result.title,
                status=result.status,
                time=time,
                line_number=-1,
                indent=parent_indent + get_indent_step(),
                body=result.body,
                children=result.subtasks,
                parent=self._source_task,
            )
            fix_parent_refs(new_task.children, new_task)
            self._children.append(new_task)
            flat = self._flat()
            self.cursor_idx = next(
                (i for i, t in enumerate(flat) if t is new_task), len(flat) - 1
            )
            self.refresh(layout=True)

        self.app.push_screen(TaskFormScreen(), on_result)

    def action_edit_subtask(self) -> None:
        flat = self._flat()
        if not flat:
            return
        selected = flat[self.cursor_idx]

        def on_result(result: TaskFormResult | None) -> None:
            if result is None:
                return
            selected.title = result.title
            selected.status = result.status
            selected.body = result.body
            if result.time_start:
                selected.time = TaskTime(
                    start=result.time_start,
                    end=result.time_end if result.time_end else None,
                )
            else:
                selected.time = None
            self.refresh()

        self.app.push_screen(TaskFormScreen(selected), on_result)

    def action_delete_subtask(self) -> None:
        flat = self._flat()
        if not flat:
            return
        target = flat[self.cursor_idx]

        def on_confirm(confirmed: bool) -> None:
            if not confirmed:
                return
            self._remove_from_tree(target, self._children)
            new_flat = self._flat()
            self.cursor_idx = min(self.cursor_idx, max(len(new_flat) - 1, 0))
            self.refresh(layout=True)

        from .save_dialog import SaveDialog
        self.app.push_screen(
            SaveDialog("Delete subtask and all its children?"),
            on_confirm,
        )

    def _remove_from_tree(self, target: Task, children: list[Task]) -> bool:
        for i, child in enumerate(children):
            if child is target:
                children.pop(i)
                return True
            if self._remove_from_tree(target, child.children):
                return True
        return False


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
        height: auto;
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
    TaskFormScreen SubtaskList {
        height: auto;
        max-height: 10;
        border: round $primary-darken-2;
        padding: 0 1;
        margin-bottom: 0;
    }
    TaskFormScreen SubtaskList:focus {
        border: round $primary;
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
                text=textwrap.dedent(task.body) if task and task.body else "",
                id="body",
            )
            yield Label("Subtasks")
            yield SubtaskList(
                task=task,
                children=task.children if task else [],
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
        subtasks = self.query_one(SubtaskList)._children
        self.dismiss(TaskFormResult(
            title=title,
            status=status,
            time_start=time_start,
            time_end=time_end,
            body=body,
            subtasks=subtasks,
        ))

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self.action_save()
        else:
            self.action_cancel()
