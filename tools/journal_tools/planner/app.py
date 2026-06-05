import datetime

from textual.app import App


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
        self.cache: dict = {}

    async def on_mount(self) -> None:
        from .week_screen import WeekScreen
        from .day_screen import DayScreen

        if self.file_path:
            await self.push_screen(DayScreen(self.directory, self.file_path, self.initial_date))
        else:
            await self.push_screen(WeekScreen(self.directory, self.cache))
