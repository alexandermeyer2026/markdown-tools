import datetime
import os
import sys

from models import Task, TaskTime
from os_utils import FileFinder, resolve_date
from parser import TaskParser
from tools.journal_tools.rendering import get_minutes, minutes_to_time

from .state import DayCache, WeekState
from .utils import read_key as _read_key, flatten_tasks as _flatten_tasks, week_expanded as _week_expanded
from .daily import render as _render, has_changes as _has_changes, save as _save
from .weekly import (
    DAY_NAMES as _DAY_NAMES,
    ensure_day_loaded as _ensure_day_loaded,
    reload_day_in_cache as _reload_day_in_cache,
    cache_has_changes as _cache_has_changes,
    save_cache as _save_cache,
    render_week as _render_week,
    shift_task as _shift_task,
)


class PlannerTool:
    STEP_SIZE_HOURS = 0.25
    DAY_NAMES = _DAY_NAMES

    # ── Entry point ───────────────────────────────────────────────────────────

    @staticmethod
    def run(args, directory='.'):
        if not args:
            PlannerTool.run_week(directory)
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

        tasks = TaskParser.parse_file(file_path)
        PlannerTool.interactive_plan(directory, file_path, tasks, date=date)

    # ── Week planner ──────────────────────────────────────────────────────────

    @staticmethod
    def run_week(directory='.'):
        today = datetime.date.today()
        week_offset = 0
        start_col = today.weekday()
        start_row = 0
        cache: dict = {}

        while True:
            monday = today - datetime.timedelta(days=today.weekday()) + datetime.timedelta(weeks=week_offset)
            week_days = [monday + datetime.timedelta(days=i) for i in range(7)]

            for day in week_days:
                _ensure_day_loaded(cache, day, directory)

            state = WeekState(week_days=week_days, directory=directory, cache=cache)

            result, start_row = PlannerTool.interactive_week(state, start_col=start_col, start_row=start_row)

            if result == 0:
                if _cache_has_changes(cache):
                    sys.stdout.write('\x1b[2J\x1b[H')
                    sys.stdout.flush()
                    if input("Save changes? [y/n]: ").strip().lower() == 'y':
                        _save_cache(cache, directory)
                        print("✓ Changes saved")
                break

            week_offset += result
            start_col = 6 if result == -1 else 0

    @staticmethod
    def interactive_week(state: WeekState, start_col: int | None = None, start_row: int = 0) -> tuple[int, int]:
        cursor_col = start_col if start_col is not None else next((i for i in range(7) if state.day(i).task_list), 0)
        cursor_row = start_row

        while True:
            _render_week(state, cursor_col, cursor_row)
            key = _read_key()

            if key in ('q', '\x03'):
                return 0, 0

            elif key == '\r':
                if cursor_row == -1:
                    col = cursor_col
                    day = state.week_days[col]
                    day_key = day.isoformat()

                    # Prompt to save pending changes so the day planner reads up-to-date files
                    if _cache_has_changes(state.cache):
                        sys.stdout.write('\x1b[2J\x1b[H')
                        sys.stdout.flush()
                        if input("Save changes? [y/n]: ").strip().lower() == 'y':
                            _save_cache(state.cache, state.directory)
                            print("✓ Changes saved")

                    # Reload the target day (file may have been created by _save_cache)
                    _reload_day_in_cache(state.cache, day, state.directory)

                    fp = state.cache[day_key].file_path
                    if fp is None:
                        fp = os.path.join(state.directory, day.strftime('%Y-%m-%d.md'))
                        open(fp, 'w').close()
                        _reload_day_in_cache(state.cache, day, state.directory)
                        fp = state.cache[day_key].file_path

                    tasks = TaskParser.parse_file(fp)
                    PlannerTool.interactive_plan(state.directory, fp, tasks, date=day)

                    # Reload the day after the day planner closes
                    _reload_day_in_cache(state.cache, day, state.directory)

            elif key == 'j':
                if cursor_row == -1:
                    cursor_row = 0
                else:
                    exp = _week_expanded(state.day(cursor_col).task_list)
                    if exp:
                        cursor_row = min(cursor_row + 1, len(exp) - 1)

            elif key == 'k':
                cursor_row = max(cursor_row - 1, -1)

            elif key == 'h':
                if cursor_col == 0:
                    return -1, 0
                cursor_col -= 1
                if cursor_row >= 0:
                    exp = _week_expanded(state.day(cursor_col).task_list)
                    cursor_row = min(cursor_row, max(len(exp) - 1, 0))

            elif key == 'l':
                if cursor_col == 6:
                    return 1, 0
                cursor_col += 1
                if cursor_row >= 0:
                    exp = _week_expanded(state.day(cursor_col).task_list)
                    cursor_row = min(cursor_row, max(len(exp) - 1, 0))

            elif key in ('t', 'i', 'd', 'f') and cursor_row >= 0:
                exp = _week_expanded(state.day(cursor_col).task_list)
                if cursor_row < len(exp):
                    exp[cursor_row].status = {'t': 'todo', 'i': 'in progress', 'd': 'done', 'f': 'failed'}[key]

            elif key == 'H' and cursor_row >= 0 and state.day(cursor_col).task_list:
                cursor_col, cursor_row, week_exit = _shift_task(state, cursor_col, cursor_row, -1)
                if week_exit:
                    return week_exit, cursor_row

            elif key == 'L' and cursor_row >= 0 and state.day(cursor_col).task_list:
                cursor_col, cursor_row, week_exit = _shift_task(state, cursor_col, cursor_row, 1)
                if week_exit:
                    return week_exit, cursor_row

            elif key == '>' and cursor_row >= 0:
                exp = _week_expanded(state.day(cursor_col).task_list)
                if cursor_row < len(exp):
                    task = exp[cursor_row]
                    if task.parent is None:
                        unfinished = [c for c in task.children if c.status not in ('done', 'failed')]
                        if unfinished:
                            task.children = [c for c in task.children if c.status in ('done', 'failed')]
                            day_key = state.week_days[cursor_col].isoformat()
                            state.cache[day_key].moved_subtasks.extend(unfinished)
                            tomorrow = state.week_days[cursor_col] + datetime.timedelta(days=1)
                            _ensure_day_loaded(state.cache, tomorrow, state.directory)
                            new_task = Task(
                                title=task.title,
                                status='todo',
                                time=None,
                                line_number=-1,
                                indent='',
                                children=list(unfinished),
                            )
                            for child in unfinished:
                                child.parent = new_task
                            tomorrow_key = tomorrow.isoformat()
                            state.cache[tomorrow_key].task_list.append(new_task)
                            state.cache[tomorrow_key].new_tasks.append(new_task)

    # ── Daily planner ─────────────────────────────────────────────────────────

    @staticmethod
    def interactive_plan(directory, file_path, tasks, date=None):
        step   = PlannerTool.STEP_SIZE_HOURS
        step_m = int(step * 60)

        timed_tasks   = sorted([t for t in tasks if t.time and t.parent is None],
                               key=lambda t: get_minutes(t.time.start))
        untimed_tasks = [t for t in tasks if not t.time and t.parent is None]
        new_tasks     = []

        original_lines = {t.line_number: t.to_line() for t in tasks if t.line_number > 0}
        cursor_idx = 0

        while True:
            navigable   = _flatten_tasks(timed_tasks + untimed_tasks)
            selected    = navigable[cursor_idx] if navigable else None
            has_changes = _has_changes(timed_tasks, untimed_tasks, original_lines, new_tasks)
            _render(file_path, timed_tasks, untimed_tasks, selected, step, directory, has_changes, date)

            key = _read_key()

            if key in ('q', '\x03'):  # q or Ctrl+C
                if has_changes:
                    sys.stdout.write('\x1b[2J\x1b[H')
                    sys.stdout.flush()
                    confirm = input("Save changes? [y/n]: ").strip().lower()
                    if confirm == 'y':
                        _save(file_path, directory, timed_tasks, untimed_tasks, original_lines, new_tasks)
                        print(f"✓ Changes saved")
                break

            elif key == 'j':
                if navigable:
                    cursor_idx = min(cursor_idx + 1, len(navigable) - 1)

            elif key == 'k':
                cursor_idx = max(cursor_idx - 1, 0)

            elif key in ('h', 'l'):
                if not navigable or selected.parent is not None:
                    continue
                direction = -1 if key == 'h' else 1

                if selected.time is None:
                    selected.time = TaskTime(start='12:00')
                    untimed_tasks.remove(selected)
                    timed_tasks.append(selected)
                    timed_tasks.sort(key=lambda t: get_minutes(t.time.start))
                else:
                    start_m = get_minutes(selected.time.start)
                    if selected.time.end:
                        end_m    = get_minutes(selected.time.end)
                        duration = end_m - start_m
                        new_start = max(0, min(start_m + direction * step_m, 24 * 60 - duration))
                        selected.time = TaskTime(
                            start=minutes_to_time(new_start),
                            end=minutes_to_time(new_start + duration),
                        )
                    else:
                        new_start = max(0, min(start_m + direction * step_m, 23 * 60 + 45))
                        selected.time = TaskTime(start=minutes_to_time(new_start))
                    timed_tasks.sort(key=lambda t: get_minutes(t.time.start))
                navigable  = _flatten_tasks(timed_tasks + untimed_tasks)
                cursor_idx = next(i for i, t in enumerate(navigable) if t is selected)

            elif key == 'H':  # shrink: move end time earlier
                if not navigable or selected.parent is not None:
                    continue
                if selected.time and selected.time.end:
                    start_m = get_minutes(selected.time.start)
                    end_m   = get_minutes(selected.time.end)
                    new_end = end_m - step_m
                    if new_end > start_m:
                        selected.time = TaskTime(start=selected.time.start,
                                                 end=minutes_to_time(new_end))
                    else:
                        selected.time = TaskTime(start=selected.time.start)

            elif key == 'L':  # extend: move end time later
                if not navigable or selected.parent is not None:
                    continue
                if selected.time:
                    if selected.time.end:
                        new_end = min(get_minutes(selected.time.end) + step_m, 24 * 60)
                    else:
                        new_end = min(get_minutes(selected.time.start) + step_m, 24 * 60)
                    selected.time = TaskTime(start=selected.time.start,
                                             end=minutes_to_time(new_end))

            elif key in ('t', 'i', 'd', 'f'):
                if selected:
                    selected.status = {'t': 'todo', 'i': 'in progress', 'd': 'done', 'f': 'failed'}[key]

            elif key == 'r':
                if navigable and selected.parent is None:
                    if selected.time and selected in timed_tasks:
                        selected.time = None
                        timed_tasks.remove(selected)
                        untimed_tasks.insert(0, selected)
                        cursor_idx = min(cursor_idx, len(_flatten_tasks(timed_tasks + untimed_tasks)) - 1)

            elif key == 'n':
                sys.stdout.write('\x1b[2J\x1b[H')
                sys.stdout.flush()
                title = input("New task title: ").strip()
                if title:
                    new_task = Task(title=title, status='todo', time=None, line_number=-1, indent='')
                    untimed_tasks.append(new_task)
                    new_tasks.append(new_task)
                    cursor_idx = len(_flatten_tasks(timed_tasks + untimed_tasks)) - 1
