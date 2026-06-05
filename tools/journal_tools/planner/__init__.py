import datetime
import os

from os_utils import FileFinder, resolve_date
from parser import TaskParser

from .app import PlannerApp
from .state import DayCache, WeekState


class PlannerTool:
    STEP_SIZE_HOURS = 0.25

    @staticmethod
    def run(args: list[str], directory: str = ".") -> None:
        if not args:
            PlannerApp(directory).run()
            return

        input_arg = args[0]
        basename = os.path.basename(input_arg)
        date = resolve_date(basename) or FileFinder.get_journal_file_date(input_arg)

        if date:
            directory = os.path.dirname(input_arg) or directory
            journal_files = FileFinder.find_journal_files(directory, date_from=date, date_to=date)
            if not journal_files:
                print(f"No journal file for {date} found")
                return
            file_path = journal_files[0]
        else:
            if not os.path.exists(input_arg):
                print(f"File {input_arg} does not exist")
                return
            file_path = input_arg

        PlannerApp(directory, file_path=file_path, date=date).run()
