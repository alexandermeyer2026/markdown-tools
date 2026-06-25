import calendar
import datetime

from rich.console import Group
from rich.text import Text
from textual.binding import Binding
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from tools.journal_tools.planner.state import PlannerState


class CalendarWidget(Widget, can_focus=True):
    DEFAULT_CSS = """
    CalendarWidget {
        width: 34;
        height: 10;
        border: solid $primary;
    }
    CalendarWidget:focus {
        border: solid $warning;
    }
    """

    BINDINGS = [
        Binding("j",     "next_week",  show=False),
        Binding("down",  "next_week",  show=False),
        Binding("k",     "prev_week",  show=False),
        Binding("up",    "prev_week",  show=False),
        Binding("h",     "prev_month", show=False),
        Binding("left",  "prev_month", show=False),
        Binding("l",     "next_month", show=False),
        Binding("right", "next_month", show=False),
        Binding("enter", "open_week",  show=False),
    ]

    selected_week: reactive[int] = reactive(0, repaint=True)

    def __init__(self, planner: PlannerState, directory: str) -> None:
        super().__init__()
        self._planner = planner
        self._directory = directory
        today = datetime.date.today()
        self._view_year = today.year
        self._view_month = today.month
        weeks = calendar.monthcalendar(today.year, today.month)
        self.selected_week = next((i for i, w in enumerate(weeks) if today.day in w), 0)

    def on_focus(self) -> None:
        hints = "[j/k] week · [h/l] month · [Enter] open · [Tab] switch · [r] refresh · [Esc] quit"
        try:
            self.screen.query_one("#hints", Static).update(Text(hints))
        except Exception:
            pass

    def _weeks(self) -> list[list[int]]:
        return calendar.monthcalendar(self._view_year, self._view_month)

    def render(self) -> Group:
        today = datetime.date.today()
        is_current = (self._view_year == today.year and self._view_month == today.month)
        weeks = self._weeks()
        month_label = datetime.date(self._view_year, self._view_month, 1).strftime('%B %Y')

        lines: list[Text] = [
            Text(f"  {month_label:^28}", style="bold"),
            Text("  Mo  Tu  We  Th  Fr  Sa  Su  ", style="bright_black"),
        ]

        for wi, week in enumerate(weeks):
            is_sel = wi == self.selected_week
            row = Text("> " if is_sel else "  ")  # cursor: no style
            for day in week:
                if day == 0:
                    row.append("    ", style="reverse" if is_sel else "")
                elif is_current and day == today.day:
                    today_style = "bold underline reverse" if is_sel else "bold underline"
                    row.append(f"{day:2d}", style=today_style)
                    row.append("  ", style="reverse" if is_sel else "")
                else:
                    row.append(f"{day:2d}  ", style="reverse" if is_sel else "")
            lines.append(row)

        return Group(*lines)

    def action_next_week(self) -> None:
        self.selected_week = min(self.selected_week + 1, len(self._weeks()) - 1)

    def action_prev_week(self) -> None:
        self.selected_week = max(self.selected_week - 1, 0)

    def action_prev_month(self) -> None:
        if self._view_month == 1:
            self._view_year -= 1
            self._view_month = 12
        else:
            self._view_month -= 1
        self.selected_week = 0
        self.refresh()

    def action_next_month(self) -> None:
        if self._view_month == 12:
            self._view_year += 1
            self._view_month = 1
        else:
            self._view_month += 1
        self.selected_week = 0
        self.refresh()

    def _week_offset(self) -> int:
        today = datetime.date.today()
        current_monday = today - datetime.timedelta(days=today.weekday())
        week = self._weeks()[self.selected_week]
        date_in_week = next(
            (datetime.date(self._view_year, self._view_month, d) for d in week if d != 0), None
        )
        if date_in_week is None:
            return 0
        sel_monday = date_in_week - datetime.timedelta(days=date_in_week.weekday())
        return (sel_monday - current_monday).days // 7

    def action_open_week(self) -> None:
        from tools.journal_tools.planner.weekly import WeekScreen

        def _on_closed(_: object) -> None:
            self.screen.reload_columns()

        self.app.push_screen(
            WeekScreen(self._planner, self._directory, self._week_offset()), _on_closed
        )
