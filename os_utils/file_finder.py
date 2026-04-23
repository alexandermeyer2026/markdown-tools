import datetime
import os
import re


class FileFinder:
    JOURNAL_FILE_PATTERN = r'(\d{4}-\d{2}-\d{2})\.md$'

    @staticmethod
    def find_journal_files(
        directory: str,
        date_from: datetime.date = None,
        date_to: datetime.date = None
    ) -> list[str]:
        file_paths = []

        for root, dirs, files in os.walk(directory):
            for file in files:
                if re.search(FileFinder.JOURNAL_FILE_PATTERN, file):
                    file_paths.append(os.path.join(root, file))

        if date_from:
            file_paths = [
                f for f in file_paths
                if FileFinder.get_journal_file_date(f) >= date_from
            ]
        if date_to:
            file_paths = [
                f for f in file_paths
                if FileFinder.get_journal_file_date(f) <= date_to
            ]

        file_paths.sort(key=lambda x: FileFinder.get_journal_file_date(x))

        return file_paths


    @staticmethod
    def get_journal_file_date(file_path: str) -> datetime.date:
        date_match = re.search(FileFinder.JOURNAL_FILE_PATTERN, file_path)

        if not date_match:
            raise ValueError(
                f"Invalid journal file path: {file_path} (no date found)"
            )

        try:
            date = datetime.datetime.strptime(
                date_match.group(1),
                "%Y-%m-%d"
            ).date()
        except ValueError:
            raise ValueError(
                f"Invalid date string: {date_match.group(1)}"
            )

        return date
