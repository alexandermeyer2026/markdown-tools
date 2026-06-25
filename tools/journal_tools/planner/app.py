import datetime

from textual.app import App

from .state import PlannerState


class PlannerApp(App):
    def __init__(
        self,
        directory: str,
        file_path: str | None = None,
        date: datetime.date | None = None,
    ):
        super().__init__()
        self.directory = directory
        self.file_path = file_path
        self.initial_date = date
        self.planner = PlannerState(directory)

    async def on_mount(self) -> None:
        from .weekly import WeekScreen
        from .daily import DayScreen

        if self.file_path:
            await self.push_screen(
                DayScreen(self.planner, self.directory, self.file_path, self.initial_date)
            )
        else:
            await self.push_screen(WeekScreen(self.planner, self.directory))
