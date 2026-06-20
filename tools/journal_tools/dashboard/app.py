import datetime

from rich.console import Group
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Rule, Static

from os_utils import FileFinder
from parser.file_model import TaskBlock, parse
from tools.journal_tools.planner.state import PlannerState
from .calendar_widget import CalendarWidget
from .column_widget import DayListColumn

_OVERDUE_DAYS  = 14
_UPCOMING_DAYS = 7

_CLOCK_DIGITS = {
    '0': ["███", "█ █", "█ █", "█ █", "███"],
    '1': [" █ ", " █ ", " █ ", " █ ", " █ "],
    '2': ["███", "  █", "███", "█  ", "███"],
    '3': ["███", "  █", "███", "  █", "███"],
    '4': ["█ █", "█ █", "███", "  █", "  █"],
    '5': ["███", "█  ", "███", "  █", "███"],
    '6': ["███", "█  ", "███", "█ █", "███"],
    '7': ["███", "  █", "  █", "  █", "  █"],
    '8': ["███", "█ █", "███", "█ █", "███"],
    '9': ["███", "█ █", "███", "  █", "███"],
    ':': ["   ", " █ ", "   ", " █ ", "   "],
}


def _gather(directory: str, date_from: datetime.date, date_to: datetime.date) -> dict:
    """Return dict[date, (file_path, list[TaskBlock])]."""
    files = FileFinder.find_journal_files(directory, date_from=date_from, date_to=date_to)
    result: dict = {}
    for f in files:
        date = FileFinder.get_journal_file_date(f)
        nodes = parse(f)
        result[date] = (f, [n for n in nodes if isinstance(n, TaskBlock)])
    return result


def _tasks_for_date(directory: str, date: datetime.date) -> tuple:
    """Return (file_path|None, list[TaskBlock])."""
    files = FileFinder.find_journal_files(directory, date_from=date, date_to=date)
    if not files:
        return None, []
    nodes = parse(files[0])
    return files[0], [n for n in nodes if isinstance(n, TaskBlock)]


class ClockWidget(Widget):
    DEFAULT_CSS = """
    ClockWidget {
        width: 25;
        height: 7;
        padding: 1 0;
    }
    """

    def on_mount(self) -> None:
        self.set_interval(60, self.refresh)

    def render(self) -> Group:
        now = datetime.datetime.now()
        time_str = now.strftime('%H:%M')
        lines: list[Text] = []
        for row in range(5):
            parts = [_CLOCK_DIGITS.get(ch, ['   '] * 5)[row] for ch in time_str]
            lines.append(Text('  ' + ' '.join(parts)))
        return Group(*lines)


class DashboardScreen(Screen):
    DEFAULT_CSS = """
    DashboardScreen {
        layout: vertical;
    }
    #date-header {
        height: 1;
        text-align: center;
        padding: 0 1;
    }
    #header {
        height: auto;
        align: center middle;
        padding: 0 2;
    }
    #columns {
        height: 1fr;
    }
    #columns Rule {
        width: 1;
        color: $primary;
        margin: 0;
    }
    #hints {
        height: 1;
        background: $primary;
        color: $background;
        padding: 0 2;
    }
    """

    BINDINGS = [
        Binding("escape", "quit", show=False),
        Binding("ctrl+c", "quit", show=False),
    ]

    def __init__(
        self,
        planner: PlannerState,
        directory: str,
        overdue_entries: list,
        today_entries: list,
        upcoming_entries: list,
    ) -> None:
        super().__init__()
        self._planner = planner
        self._directory = directory
        self._overdue = overdue_entries
        self._today = today_entries
        self._upcoming = upcoming_entries

    def compose(self) -> ComposeResult:
        today = datetime.date.today()
        week_num = today.isocalendar()[1]
        date_label = f"{today.strftime('%A, %-d %B %Y')}  ·  Week {week_num}"
        yield Static(Text(date_label, style="bold"), id="date-header")
        with Horizontal(id="header"):
            yield ClockWidget()
            yield CalendarWidget(self._planner, self._directory)
        with Horizontal(id="columns"):
            yield DayListColumn("Overdue",  self._overdue,   self._planner, self._directory)
            yield Rule(orientation="vertical")
            yield DayListColumn("Today",    self._today,     self._planner, self._directory)
            yield Rule(orientation="vertical")
            yield DayListColumn("Upcoming", self._upcoming,  self._planner, self._directory)
        yield Static("", id="hints")

    def on_mount(self) -> None:
        self.query_one(CalendarWidget).focus()

    def reload_columns(self) -> None:
        today = datetime.date.today()
        overdue_by_date = _gather(
            self._directory,
            today - datetime.timedelta(days=_OVERDUE_DAYS),
            today - datetime.timedelta(days=1),
        )
        fp_today, today_blocks = _tasks_for_date(self._directory, today)
        upcoming_by_date = _gather(
            self._directory,
            today + datetime.timedelta(days=1),
            today + datetime.timedelta(days=_UPCOMING_DAYS),
        )
        self._overdue = [
            (d, fp, [b for b in blocks if b.task.status in ('todo', 'in progress', 'started')])
            for d, (fp, blocks) in sorted(overdue_by_date.items())
            if any(b.task.status in ('todo', 'in progress', 'started') for b in blocks)
        ]
        self._today = [(today, fp_today, today_blocks)]
        self._upcoming = [
            (d, fp, blocks)
            for d, (fp, blocks) in sorted(upcoming_by_date.items())
            if blocks
        ]
        columns = self.query_one("#columns")
        columns.remove_children()
        columns.mount(
            DayListColumn("Overdue",  self._overdue,   self._planner, self._directory),
            Rule(orientation="vertical"),
            DayListColumn("Today",    self._today,     self._planner, self._directory),
            Rule(orientation="vertical"),
            DayListColumn("Upcoming", self._upcoming,  self._planner, self._directory),
        )

    def action_quit(self) -> None:
        self.app.exit()


class DashboardApp(App):
    def __init__(self, directory: str) -> None:
        super().__init__()
        today = datetime.date.today()

        overdue_by_date = _gather(
            directory,
            today - datetime.timedelta(days=_OVERDUE_DAYS),
            today - datetime.timedelta(days=1),
        )
        fp_today, today_blocks = _tasks_for_date(directory, today)
        upcoming_by_date = _gather(
            directory,
            today + datetime.timedelta(days=1),
            today + datetime.timedelta(days=_UPCOMING_DAYS),
        )

        self._overdue = [
            (d, fp, [b for b in blocks if b.task.status in ('todo', 'in progress', 'started')])
            for d, (fp, blocks) in sorted(overdue_by_date.items())
            if any(b.task.status in ('todo', 'in progress', 'started') for b in blocks)
        ]
        self._today = [(today, fp_today, today_blocks)]
        self._upcoming = [
            (d, fp, blocks)
            for d, (fp, blocks) in sorted(upcoming_by_date.items())
            if blocks
        ]
        self._planner = PlannerState(directory)
        self._directory = directory

    async def on_mount(self) -> None:
        await self.push_screen(
            DashboardScreen(
                self._planner, self._directory,
                self._overdue, self._today, self._upcoming,
            )
        )
