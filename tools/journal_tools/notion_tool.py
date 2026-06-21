import csv
import os
import sys

from config import get_indent_step
from models import Task, TaskTime
from os_utils import BackupManager, FileFinder
from os_utils.file_writer import FileWriter
from parser.file_model import RawLine, TaskBlock, parse, serialize


CSV_FIELDNAMES = ['Title', 'Status', 'Date', 'Time Start', 'Time End', 'Priority', 'Tags', 'Depth']


def _task_to_row(task: Task, date: str, depth: int) -> dict:
    return {
        'Title': task.title,
        'Status': task.status or '',
        'Date': date,
        'Time Start': task.time.start if task.time else '',
        'Time End': task.time.end if task.time and task.time.end else '',
        'Priority': task.priority or '',
        'Tags': ','.join(task.tags) if task.tags else '',
        'Depth': depth,
    }


def _collect_rows(nodes: list, date: str, depth: int = 0) -> list[dict]:
    rows = []
    for node in nodes:
        if isinstance(node, TaskBlock):
            rows.append(_task_to_row(node.task, date, depth))
            rows.extend(_collect_rows(node.nodes, date, depth + 1))
    return rows


def _row_to_task_block(row: dict) -> TaskBlock:
    indent = get_indent_step() * int(row['Depth'])
    time_start = row['Time Start'].strip()
    time_end = row['Time End'].strip()
    task_time = None
    if time_start:
        task_time = TaskTime(start=time_start, end=time_end if time_end else None)

    tags_str = row['Tags'].strip()
    tags = [t.strip() for t in tags_str.split(',') if t.strip()] if tags_str else []

    task = Task(
        title=row['Title'],
        status=row['Status'] if row['Status'] else None,
        time=task_time,
        line_number=-1,
        indent=indent,
        priority=row['Priority'].strip() if row['Priority'].strip() else None,
        tags=tags,
    )
    block = TaskBlock(task=task, header='')
    block.refresh_header()
    if tags:
        block.refresh_tags()
    return block


def _rows_to_nodes(rows: list[dict]) -> list:
    top = []
    stack = []  # (depth, TaskBlock)
    for row in rows:
        block = _row_to_task_block(row)
        depth = int(row['Depth'])
        while stack and stack[-1][0] >= depth:
            stack.pop()
        if stack:
            stack[-1][1].nodes.append(block)
        else:
            top.append(block)
        stack.append((depth, block))
    return top


def _replace_task_runs(original_nodes: list, new_task_nodes: list) -> list:
    result = []
    tasks_placed = False
    for node in original_nodes:
        if isinstance(node, TaskBlock):
            if not tasks_placed:
                result.extend(new_task_nodes)
                tasks_placed = True
        else:
            result.append(node)
    if not tasks_placed:
        result.extend(new_task_nodes)
    return result


class NotionTool:
    @staticmethod
    def export(args: list[str], journal_dir: str) -> None:
        output_path = args[0] if args else 'notion_export.csv'

        files = FileFinder.find_journal_files(journal_dir)
        rows = []
        for file_path in files:
            date = FileFinder.get_journal_file_date(file_path)
            nodes = parse(file_path)
            rows.extend(_collect_rows(nodes, date.isoformat()))

        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
            writer.writeheader()
            writer.writerows(rows)

        print(f"Exported {len(rows)} tasks from {len(files)} files → {output_path}")

    @staticmethod
    def import_(args: list[str], journal_dir: str) -> None:
        if not args:
            print("Usage: journal notion-import <input.csv>")
            sys.exit(1)

        input_path = args[0]
        with open(input_path, 'r', newline='', encoding='utf-8') as f:
            rows = list(csv.DictReader(f))

        by_date: dict[str, list[dict]] = {}
        for row in rows:
            by_date.setdefault(row['Date'], []).append(row)

        all_files = {
            FileFinder.get_journal_file_date(fp).isoformat(): fp
            for fp in FileFinder.find_journal_files(journal_dir)
        }

        matched = {date: all_files[date] for date in by_date if date in all_files}
        skipped = [date for date in by_date if date not in all_files]

        if not matched:
            print("No matching journal files found.")
            return

        print(f"Will overwrite tasks in {len(matched)} files:")
        for date in sorted(matched):
            print(f"  {date}.md — {len(by_date[date])} tasks")
        for date in skipped:
            print(f"  Warning: no journal file for {date}, skipping")

        answer = input("Proceed? [y/N] ").strip().lower()
        if answer != 'y':
            print("Aborted.")
            return

        updated = 0
        for date in sorted(matched):
            file_path = matched[date]
            nodes = parse(file_path)
            new_task_nodes = _rows_to_nodes(by_date[date])
            new_nodes = _replace_task_runs(nodes, new_task_nodes)
            content = serialize(new_nodes)

            BackupManager.backup(file_path, journal_dir)
            FileWriter.write_atomic(file_path, content.splitlines(keepends=True))
            print(f"  Updated {date}.md")
            updated += 1

        print(f"Import complete: {updated} files updated.")
