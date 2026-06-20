import datetime
import os

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.widget import Widget
from textual.widgets import Rule, Static
from rich.console import Group

from parser.file_model import TaskBlock
from tools.journal_tools.rendering import STATUS_ICONS, STATUS_STYLES
from models import get_minutes
from tools.journal_tools.planner.state import PlannerState


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
    Static {
        height: auto;
        width: 1fr;
    }
    """

    BINDINGS = [Binding("enter", "open_day", show=False)]

    def __init__(
        self,
        date: datetime.date,
        fp,
        blocks: list,
        planner: PlannerState,
        directory: str,
    ) -> None:
        super().__init__()
        self._date = date
        self._fp = fp
        self._blocks = blocks
        self._planner = planner
        self._directory = directory

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
        yield Static(Text(self._date_label(), style="bold"))

        today    = datetime.date.today()
        tomorrow = today + datetime.timedelta(days=1)
        timed    = sorted([b for b in self._blocks if b.task.time],
                          key=lambda b: get_minutes(b.task.time.start))
        untimed  = [b for b in self._blocks if not b.task.time]

        if timed and self._date in (today, tomorrow):
            from tools.journal_tools.timeline_tool import TimelineTool
            width = max(20, self.app.size.width // 3 - 4)
            for line in TimelineTool.render_timeline_lines(timed, self._date, width):
                yield Static(Text.from_ansi(line))
        else:
            for block in timed:
                task  = block.task
                icon  = STATUS_ICONS.get(task.status, "○")
                style = STATUS_STYLES.get(task.status, "bright_black")
                t = Text("  ")
                t.append(icon, style=style)
                t.append(f"  {task.time.to_str()}  {task.title}")
                yield Static(t)
                yield from self._subtask_statics(block)

        for block in untimed:
            task  = block.task
            icon  = STATUS_ICONS.get(task.status, "○")
            style = STATUS_STYLES.get(task.status, "bright_black")
            t = Text("  ")
            t.append(icon, style=style)
            t.append(f"  {task.title}")
            yield Static(t)
            yield from self._subtask_statics(block)

    def _subtask_statics(self, block: TaskBlock, depth: int = 1):
        for child_block in [n for n in block.nodes if isinstance(n, TaskBlock)]:
            child = child_block.task
            icon = STATUS_ICONS.get(child.status, "?")
            style = STATUS_STYLES.get(child.status, "bright_black")
            t = Text(f"  {'  ' * depth}")
            t.append(icon, style=style)
            t.append(f"  {child.title}")
            yield Static(t)
            yield from self._subtask_statics(child_block, depth + 1)

    def on_focus(self) -> None:
        hints = "[Enter] open day · [Tab] next day · [Esc] quit"
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
            open(fp, "w").close()
            self._planner.reload_day_by_key(day_key, new_file_path=fp)
            fp = self._planner.days[day_key].file_path

        from tools.journal_tools.planner.day_screen import DayScreen

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
    ) -> None:
        super().__init__()
        self._title = title
        self._entries = entries
        self._planner = planner
        self._directory = directory

    def compose(self) -> ComposeResult:
        total = sum(len(blocks) for _, _, blocks in self._entries)
        header = f"{self._title}{'  ·  ' + str(total) if total else ''}"
        yield ColumnHeader(header)

        if not self._entries:
            yield Static(Text("  –", style="bright_black"))
        else:
            for date, fp, blocks in self._entries:
                yield DayEntry(date, fp, blocks, self._planner, self._directory)
