import datetime
import sys
import uuid

from os_utils import FileFinder
from models.file import TaskBlock, parse
from tools.journal_tools.cli_utils import parse_date_flags


STATUS_MAP = {
    'todo':        'TENTATIVE',
    'in progress': 'CONFIRMED',
    'started':     'CONFIRMED',
    'done':        'CONFIRMED',
    'failed':      'CANCELLED',
}

PRIORITY_MAP = {
    '!':   '9',
    '!!':  '5',
    '!!!': '1',
}


def _escape(text: str) -> str:
    return (
        text
        .replace('\\', '\\\\')
        .replace(',',  '\\,')
        .replace(';',  '\\;')
        .replace('\n', '\\n')
    )


def _parse_time(t: str) -> datetime.time:
    h, m = t.split(':')
    return datetime.time(int(h), int(m))


def _make_uid(date: str, idx: int) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f'journal:{date}:{idx}'))


def _task_to_vevent_lines(task, date: datetime.date, idx: int) -> list[str]:
    lines = [
        'BEGIN:VEVENT',
        f'UID:{_make_uid(date.isoformat(), idx)}',
        f'SUMMARY:{_escape(task.title)}',
        f'STATUS:{STATUS_MAP.get(task.status or "", "TENTATIVE")}',
        f'PRIORITY:{PRIORITY_MAP.get(task.priority or "", "0")}',
    ]

    if task.time and task.time.start:
        start_dt = datetime.datetime.combine(date, _parse_time(task.time.start))
        lines.append(f'DTSTART:{start_dt.strftime("%Y%m%dT%H%M%S")}')
        if task.time.end:
            end_dt = datetime.datetime.combine(date, _parse_time(task.time.end))
        else:
            end_dt = start_dt + datetime.timedelta(hours=1)
        lines.append(f'DTEND:{end_dt.strftime("%Y%m%dT%H%M%S")}')
    else:
        lines.append(f'DTSTART;VALUE=DATE:{date.strftime("%Y%m%d")}')
        lines.append(f'DTEND;VALUE=DATE:{(date + datetime.timedelta(days=1)).strftime("%Y%m%d")}')

    if task.tags:
        lines.append(f'CATEGORIES:{",".join(_escape(t) for t in task.tags)}')

    lines.append('END:VEVENT')
    return lines


def _collect_vevent_lines(nodes: list, date: datetime.date, counter: list) -> list[list[str]]:
    events = []
    for node in nodes:
        if isinstance(node, TaskBlock):
            events.append(_task_to_vevent_lines(node.task, date, counter[0]))
            counter[0] += 1
            events.extend(_collect_vevent_lines(node.nodes, date, counter))
    return events


def _build_ics(all_events: list[list[str]]) -> str:
    lines = [
        'BEGIN:VCALENDAR',
        'VERSION:2.0',
        'PRODID:-//markdown-tools//journal//EN',
        'CALSCALE:GREGORIAN',
        'X-WR-CALNAME:Journal',
    ]
    for event_lines in all_events:
        lines.extend(event_lines)
    lines.append('END:VCALENDAR')
    return '\r\n'.join(lines) + '\r\n'


class IcsTool:
    @staticmethod
    def export(args: list[str], journal_dir: str) -> None:
        positional, date_from, date_to = parse_date_flags(args)
        output_path = positional[0] if positional else 'journal_export.ics'

        files = FileFinder.find_journal_files(journal_dir, date_from=date_from, date_to=date_to)
        all_events = []
        counter = [0]
        for file_path in files:
            date = FileFinder.get_journal_file_date(file_path)
            nodes = parse(file_path)
            all_events.extend(_collect_vevent_lines(nodes, date, counter))

        with open(output_path, 'w', encoding='utf-8', newline='') as f:
            f.write(_build_ics(all_events))

        print(f"Exported {len(all_events)} events from {len(files)} files → {output_path}")
