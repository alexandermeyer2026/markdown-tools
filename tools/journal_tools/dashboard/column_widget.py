import datetime
import os

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Rule, Static
from rich.console import Group

from models.file import TaskBlock
from os_utils import FileWriter
from tools.journal_tools.rendering import STATUS_ICONS, STATUS_STYLES, ansi_truncate
from models import get_minutes
from tools.journal_tools.planner.state import PlannerState


class TimelineWidget(Widget):
    DEFAULT_CSS = """
    TimelineWidget {
        height: auto;
    }
    """

    def __init__(self, blocks: list, date: datetime.date, collapsed: bool = False) -> None:
        super().__init__()
        self._blocks = blocks
        self._date = date
        self._collapsed = collapsed

    def _timeline_lines(self, width: int) -> list[str]:
        from tools.journal_tools.timeline_tool import TimelineTool
        lines = TimelineTool.render_timeline_lines(self._blocks, self._date, max(20, width), self._collapsed)
        return [ansi_truncate(line, width) for line in lines]

    def get_content_height(self, container, viewport, width: int) -> int:
        return len(self._timeline_lines(width))

    def render(self) -> Text:
        return Text.from_ansi('\n'.join(self._timeline_lines(self.size.width)))


class TaskRowWidget(Widget):
    DEFAULT_CSS = """
    TaskRowWidget {
        height: 1;
        width: 1fr;
    }
    """

    def __init__(self, text: Text) -> None:
        super().__init__()
        self._text = text

    def render(self) -> Text:
        return self._text[:self.size.width]


class ColumnHeader(Widget):
    DEFAULT_CSS = """
    ColumnHeader {
        height: 1;
    }
    """

    def __init__(self, title: str) -> None:
        super().__init__()
        self._title = title

    def render(self) -> Group:
        w = max(self.size.width, len(self._title) + 5)
        bar = "─" * max(0, w - len(self._title) - 4)
        t = Text()
        t.append("── ", style="bright_black")
        t.append(self._title, style="bold")
        t.append(" " + bar, style="bright_black")
        return Group(t)


class DayEntry(Widget, can_focus=True):
    DEFAULT_CSS = """
    DayEntry {
        height: auto;
        border: blank;
        padding: 0 1;
    }
    DayEntry:focus {
        border: solid $warning;
    }
"""

    BINDINGS = [Binding("enter", "open_day", show=False)]

    collapsed: reactive[bool] = reactive(False, recompose=True)

    def __init__(
        self,
        date: datetime.date,
        fp,
        blocks: list,
        planner: PlannerState,
        directory: str,
        collapsed: bool = False,
    ) -> None:
        super().__init__()
        self._date = date
        self._fp = fp
        self._blocks = blocks
        self._planner = planner
        self._directory = directory
        self.collapsed = collapsed

    def _date_label(self) -> str:
        today = datetime.date.today()
        delta = (self._date - today).days
        if delta == 0:
            return f"Today, {self._date.strftime('%-d %b')}"
        elif delta == 1:
            return f"Tomorrow, {self._date.strftime('%-d %b')}"
        else:
            return self._date.strftime('%A, %-d %b')

    def compose(self) -> ComposeResult:
        yield TaskRowWidget(Text(self._date_label(), style="bold"))

        today    = datetime.date.today()
        tomorrow = today + datetime.timedelta(days=1)
        timed    = sorted([b for b in self._blocks if b.task.time],
                          key=lambda b: get_minutes(b.task.time.start))
        untimed  = [b for b in self._blocks if not b.task.time]

        if timed and self._date in (today, tomorrow):
            yield TimelineWidget(timed, self._date, self.collapsed)
        else:
            for block in timed:
                task  = block.task
                icon  = STATUS_ICONS.get(task.status, "○")
                style = STATUS_STYLES.get(task.status, "bright_black")
                t = Text("  ")
                t.append(icon, style=style)
                t.append(f"  {task.time.to_str()}  {task.title}")
                yield TaskRowWidget(t)
                if not self.collapsed:
                    yield from self._subtask_statics(block)

        for block in untimed:
            task  = block.task
            icon  = STATUS_ICONS.get(task.status, "○")
            style = STATUS_STYLES.get(task.status, "bright_black")
            t = Text("  ")
            t.append(icon, style=style)
            t.append(f"  {task.title}")
            yield TaskRowWidget(t)
            if not self.collapsed:
                yield from self._subtask_statics(block)

    def _subtask_statics(self, block: TaskBlock, depth: int = 1):
        for child_block in [n for n in block.nodes if isinstance(n, TaskBlock)]:
            child = child_block.task
            icon = STATUS_ICONS.get(child.status, "?")
            style = STATUS_STYLES.get(child.status, "bright_black")
            t = Text(f"  {'  ' * depth}")
            t.append(icon, style=style)
            t.append(f"  {child.title}")
            yield TaskRowWidget(t)
            yield from self._subtask_statics(child_block, depth + 1)

    def on_focus(self) -> None:
        toggle_label = "expand" if self.collapsed else "collapse"
        hints = f"[Enter] open day · [Tab] next day · [c] {toggle_label} · [ctrl+r] refresh · [Esc] quit"
        try:
            self.screen.query_one("#hints", Static).update(Text(hints))
        except Exception:
            pass

    def action_open_day(self) -> None:
        day_key = self._date.isoformat()
        cache = self._planner.load_day(self._date)

        fp = cache.file_path
        if fp is None:
            fp = os.path.join(self._directory, self._date.strftime("%Y-%m-%d.md"))
            FileWriter.touch(fp)
            self._planner.reload_day_by_key(day_key, new_file_path=fp)
            fp = self._planner.days[day_key].file_path

        from tools.journal_tools.planner.daily import DayScreen

        def _on_closed(_: object) -> None:
            self._planner.reload_day_by_key(day_key)
            self.screen.reload_columns()

        self.app.push_screen(DayScreen(self._planner, self._directory, fp, self._date), _on_closed)


class DayListColumn(Widget):
    DEFAULT_CSS = """
    DayListColumn {
        width: 1fr;
        height: 1fr;
        overflow-y: auto;
    }
    DayListColumn Rule {
        margin: 0;
        color: $primary;
        height: 1fr;
    }
    """

    def __init__(
        self,
        title: str,
        entries: list,
        planner: PlannerState,
        directory: str,
        collapsed: bool = False,
    ) -> None:
        super().__init__()
        self._title = title
        self._entries = entries
        self._planner = planner
        self._directory = directory
        self._collapsed = collapsed

    def compose(self) -> ComposeResult:
        total = sum(len(blocks) for _, _, blocks in self._entries)
        header = f"{self._title}{'  ·  ' + str(total) if total else ''}"
        yield ColumnHeader(header)

        if not self._entries:
            yield Static(Text("  –", style="bright_black"))
        else:
            for date, fp, blocks in self._entries:
                yield DayEntry(date, fp, blocks, self._planner, self._directory, self._collapsed)
