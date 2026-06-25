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
from models.file import RawLine, TaskBlock, remove_block
from tools.journal_tools.rendering import STATUS_ICONS


@dataclass
class TaskFormResult:
    title: str
    status: str
    time_start: str | None
    time_end: str | None
    body: str | None
    subtasks: list = field(default_factory=list)  # list[TaskBlock]


_STATUS_OPTIONS: list[tuple[str, str]] = [
    ("○  Todo",        "todo"),
    ("◐  In progress", "in progress"),
    ("~  Started",     "started"),
    ("✓  Done",        "done"),
    ("✗  Failed",      "failed"),
]


def _flat_blocks(blocks: list) -> list:
    """DFS flat list of all TaskBlocks."""
    result = []
    for block in blocks:
        if isinstance(block, TaskBlock):
            result.append(block)
            result.extend(_flat_blocks([n for n in block.nodes if isinstance(n, TaskBlock)]))
    return result


class SubtaskList(Widget, can_focus=True):
    BINDINGS = [
        Binding("j",     "cursor_down",    show=False),
        Binding("k",     "cursor_up",      show=False),
        Binding("n",     "add_subtask",    show=False),
        Binding("enter", "edit_subtask",   show=False),
        Binding("backspace", "delete_subtask", show=False),
    ]

    cursor_idx: reactive[int] = reactive(0, repaint=True)

    def __init__(self, parent_task: Task | None, children: list) -> None:
        super().__init__()
        self._parent_task = parent_task
        self._children = children  # list[TaskBlock]

    def _flat(self) -> list:
        return _flat_blocks(self._children)

    def get_content_height(self, container_size, viewport_size, width: int) -> int:
        return max(len(self._flat()), 1)

    def render(self) -> Group | Text:
        flat = self._flat()
        if not flat:
            return Text("  press n to add", style="dim")
        cursor_block = flat[min(self.cursor_idx, len(flat) - 1)]
        lines = self._render_children(self._children, depth=0, cursor_block=cursor_block)
        return Group(*lines)

    def _render_children(
        self, blocks: list, depth: int, cursor_block
    ) -> list[Text]:
        lines = []
        for block in blocks:
            icon = STATUS_ICONS.get(block.task.status, "?")
            indent = "  " * depth
            is_sel = block is cursor_block and self.has_focus
            t = Text(indent + icon + " " + block.task.title)
            if is_sel:
                t.stylize("reverse")
            lines.append(t)
            child_blocks = [n for n in block.nodes if isinstance(n, TaskBlock)]
            lines.extend(self._render_children(child_blocks, depth + 1, cursor_block))
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
            parent_indent = self._parent_task.indent if self._parent_task else ""
            new_task = Task(
                title=result.title,
                status=result.status,
                time=time,
                line_number=-1,
                indent=parent_indent + get_indent_step(),
            )
            new_block = TaskBlock.from_task(new_task, result.body, result.subtasks)
            self._children.append(new_block)
            flat = self._flat()
            self.cursor_idx = next(
                (i for i, b in enumerate(flat) if b is new_block), len(flat) - 1
            )
            self.refresh(layout=True)

        self.app.push_screen(TaskFormScreen(), on_result)

    def action_edit_subtask(self) -> None:
        flat = self._flat()
        if not flat:
            return
        selected_block = flat[self.cursor_idx]

        def on_result(result: TaskFormResult | None) -> None:
            if result is None:
                return
            new_time = (TaskTime(start=result.time_start,
                                  end=result.time_end if result.time_end else None)
                        if result.time_start else None)
            selected_block.set_status(result.status)
            selected_block.set_time(new_time)
            selected_block.set_title(result.title)
            selected_block.set_body_and_subtasks(result.body, result.subtasks)
            self.refresh(layout=True)

        self.app.push_screen(TaskFormScreen(selected_block), on_result)

    def action_delete_subtask(self) -> None:
        flat = self._flat()
        if not flat:
            return
        target = flat[self.cursor_idx]

        def on_confirm(confirmed: bool) -> None:
            if not confirmed:
                return
            remove_block(self._children, target)
            new_flat = self._flat()
            self.cursor_idx = min(self.cursor_idx, max(len(new_flat) - 1, 0))
            self.refresh(layout=True)

        from .save_dialog import SaveDialog
        self.app.push_screen(
            SaveDialog("Delete subtask and all its children?"),
            on_confirm,
        )


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

    def __init__(self, block: TaskBlock | None = None):
        super().__init__()
        self._source_block = block

    def compose(self) -> ComposeResult:
        block = self._source_block
        task = block.task if block else None
        body_str = ""
        child_blocks: list = []
        if block:
            body_lines = [n.raw.rstrip('\n') for n in block.nodes if isinstance(n, RawLine)]
            while body_lines and not body_lines[-1].strip():
                body_lines.pop()
            body_str = textwrap.dedent('\n'.join(body_lines))
            child_blocks = [n for n in block.nodes if isinstance(n, TaskBlock)]
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
                text=body_str,
                id="body",
            )
            yield Label("Subtasks")
            yield SubtaskList(
                parent_task=task,
                children=child_blocks,
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
        body = self.query_one("#body", TextArea).text.lstrip('\n') or None
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
