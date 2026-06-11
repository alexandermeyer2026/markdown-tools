import datetime
import os

from rich.console import Group
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.reactive import reactive
from textual.screen import Screen
from textual.widget import Widget

from models import Task, TaskTime, get_minutes, minutes_to_time
from tools.journal_tools.rendering import (
    STATUS_ICONS, STATUS_STYLES, get_time_slot, scale_lines,
)
from .daily import has_changes, save
from .state import DayCache, PlannerState
from .utils import flatten_tasks, fix_parent_refs

_STEP = 0.25          # hours per slot (15 min)
_STEP_M = int(_STEP * 60)
_MARGIN = "  "


class DayGrid(Widget, can_focus=True):
    DEFAULT_CSS = """
    DayGrid {
        width: 1fr;
        height: 1fr;
    }
    """

    BINDINGS = [
        Binding("j",     "cursor_down",   show=False),
        Binding("k",     "cursor_up",     show=False),
        Binding("h",     "shift_left",    show=False),
        Binding("l",     "shift_right",   show=False),
        Binding("H",     "shrink_end",    show=False),
        Binding("L",     "extend_end",    show=False),
        Binding("r",     "remove_time",   show=False),
        Binding("t",      "status_todo",        show=False),
        Binding("i",      "status_in_progress", show=False),
        Binding("s",      "status_started",     show=False),
        Binding("d",      "status_done",        show=False),
        Binding("f",      "status_failed",      show=False),
        Binding("enter",  "edit_task",          show=False),
        Binding("n",      "new_task",           show=False),
        Binding("D",      "delete_task",        show=False),
        Binding("ctrl+s", "save",               show=False),
        Binding("q",     "quit",          show=False),
        Binding("ctrl+c","quit",          show=False),
    ]

    cursor_idx: reactive[int] = reactive(0, repaint=True)

    def __init__(
        self,
        planner: PlannerState,
        directory: str,
        file_path: str,
        date: datetime.date | None,
    ):
        super().__init__()
        self._planner = planner
        self._directory = directory
        self._file_path = file_path
        self._date = date
        self._day_key: str | None = None

    def on_mount(self) -> None:
        self._day_key, _ = self._planner.load_file(self._file_path, self._date)

    # ── State accessors ───────────────────────────────────────────────────────

    def _day(self) -> DayCache:
        assert self._day_key is not None
        return self._planner.days[self._day_key]

    @property
    def _timed_tasks(self) -> list[Task]:
        return sorted(
            [t for t in self._day().task_list if t.time],
            key=lambda t: get_minutes(t.time.start),
        )

    @property
    def _untimed_tasks(self) -> list[Task]:
        return [t for t in self._day().task_list if not t.time]

    @property
    def _new_tasks(self) -> list[Task]:
        return [t for t in self._day().task_list if t.line_number == -1]

    @property
    def _deleted_tasks(self) -> list[Task]:
        return list(self._day().deleted_tasks)

    # ── Rendering ─────────────────────────────────────────────────────────────

    def render(self) -> Group:
        timed = self._timed_tasks
        untimed = self._untimed_tasks
        navigable = flatten_tasks(timed + untimed)
        selected = navigable[self.cursor_idx] if navigable else None

        rel_path = os.path.relpath(self._file_path, self._directory)
        marker = " *" if self._has_changes() else ""

        lines: list[Text] = [
            Text.assemble(_MARGIN, (f"Planning: {rel_path}{marker}", "bold")),
            Text(""),
        ]

        if timed:
            now_slot = None
            if self._date and self._date == datetime.date.today():
                now_m = datetime.datetime.now().hour * 60 + datetime.datetime.now().minute
                now_slot = get_time_slot(now_m, _STEP)

            hours_str, scale_str = scale_lines(_STEP, 0, now_slot)
            hours_text = Text(_MARGIN + hours_str)
            scale_text = Text(_MARGIN + scale_str, style="bright_black")
            if now_slot is not None:
                now_col = len(_MARGIN) + now_slot
                scale_text.stylize("white", now_col, now_col + 1)
                hours_text = self._insert_now_col(hours_text, now_col)
            lines.append(hours_text)
            lines.append(scale_text)

            for task in timed:
                start_slot = get_time_slot(get_minutes(task.time.start), _STEP)
                end_slot = start_slot
                if task.time.end:
                    end_slot = get_time_slot(get_minutes(task.time.end) - 1, _STEP)
                bar_width = max(end_slot - start_slot + 1, 1)
                icon_col = start_slot + bar_width + len(task.time.to_str()) + 2
                task_row = self._timed_task_row(task, selected)
                task_body = self._body_rows(task, time_offset=icon_col)
                task_subs = self._subtask_rows(task, selected, time_offset=icon_col)
                if now_slot is not None:
                    task_row = self._insert_now_col(task_row, now_col)
                    task_body = [self._insert_now_col(l, now_col) for l in task_body]
                    task_subs = [self._insert_now_col(l, now_col) for l in task_subs]
                lines.append(task_row)
                lines.extend(task_body)
                lines.extend(task_subs)
        else:
            lines.append(Text.assemble(_MARGIN, ("No timed tasks yet", "bright_black")))

        if untimed:
            lines.append(Text(""))
            lines.append(
                Text.assemble(_MARGIN, ("── Unscheduled " + "─" * 50, "bright_black"))
            )
            for task in untimed:
                lines.append(self._untimed_task_row(task, selected))
                lines.extend(self._body_rows(task))
                lines.extend(self._subtask_rows(task, selected))

        if not timed and not untimed:
            lines.append(Text(""))
            lines.append(
                Text.assemble(_MARGIN, ("No tasks. Press n to add one.", "bright_black"))
            )

        lines.append(Text(""))
        hints = (
            "[j/k] move  [h/l] shift  [H/L] end time  [r] remove time  "
            "[n] new  [Enter] edit  [t/i/s/d/f] status  [ctrl+s] save  [q] back"
        )
        lines.append(Text(_MARGIN + hints, style="bright_black"))

        return Group(*lines)

    def _timed_task_row(self, task: Task, selected: Task | None) -> Text:
        icon = STATUS_ICONS.get(task.status, "?")
        style = STATUS_STYLES.get(task.status, "bright_black")
        is_sel = task is selected

        start_m = get_minutes(task.time.start)
        start_slot = get_time_slot(start_m, _STEP)
        end_slot = start_slot
        if task.time.end:
            end_m = get_minutes(task.time.end)
            end_slot = get_time_slot(end_m - 1, _STEP)
        bar_width = max(end_slot - start_slot + 1, 1)
        offset = start_slot

        icon_col = offset + bar_width + len(task.time.to_str()) + 2
        title_max = max(self.size.width - icon_col - 4, 0)

        if is_sel:
            t = Text(" " * offset + "> ")
        else:
            t = Text(_MARGIN + " " * offset)
        t.append("█" * bar_width, style=style)
        t.append(f" {task.time.to_str()} ")
        t.append(icon, style=style)
        t.append(" ")
        t.append(task.title[:title_max], style="bold reverse" if is_sel else "bold")
        return t

    def _untimed_task_row(self, task: Task, selected: Task | None) -> Text:
        icon = STATUS_ICONS.get(task.status, "?")
        style = STATUS_STYLES.get(task.status, "bright_black")
        is_sel = task is selected
        title_max = max(self.size.width - 4, 0)
        t = Text("> " if is_sel else "  ")
        t.append(icon, style=style)
        t.append(" ")
        t.append(task.title[:title_max], style="bold reverse" if is_sel else "bold")
        return t

    def _body_rows(self, task: Task, depth: int = 0, time_offset: int = 0) -> list[Text]:
        if not task.body:
            return []
        rows = []
        prefix = " " * time_offset + "  " * (depth + 1)
        for line in task.body.split('\n'):
            stripped = line.strip()
            if stripped:
                t = Text(_MARGIN + prefix)
                t.append(stripped, style="bright_black italic")
                rows.append(t)
        return rows

    def _subtask_rows(self, task: Task, selected: Task | None, depth: int = 1, time_offset: int = 0) -> list[Text]:
        rows: list[Text] = []
        for child in task.children:
            icon = STATUS_ICONS.get(child.status, "?")
            leading = " " * time_offset + "  " * depth
            title_max = max(self.size.width - len(leading) - 4, 0)
            t = Text(_MARGIN)
            if child is selected:
                t.append(leading[:-2] if len(leading) >= 2 else leading)
                t.append("> ")
                t.append(icon)
                t.append(" ")
                t.append(child.title[:title_max], style="reverse")
            else:
                t.append(leading)
                t.append(icon, style="bright_black")
                t.append(f" {child.title[:title_max]}", style="bright_black")
            rows.append(t)
            rows.extend(self._body_rows(child, depth, time_offset))
            rows.extend(self._subtask_rows(child, selected, depth + 1, time_offset))
        return rows

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _insert_now_col(t: Text, col: int) -> Text:
        plain = t.plain
        content_start = next((i for i, c in enumerate(plain) if c != ' '), len(plain))
        if col >= content_start and col < len(plain):
            return t  # col lands inside content — skip
        if col >= len(plain):
            pad = col - len(plain)
            return Text.assemble(t, Text(" " * pad + "│", style="bright_black"))
        # col is in leading blank margin
        return Text.assemble(t[:col], Text("│", style="bright_black"), t[col + 1:])

    def _navigable(self) -> list[Task]:
        return flatten_tasks(self._timed_tasks + self._untimed_tasks)

    def _selected(self) -> Task | None:
        nav = self._navigable()
        if nav and 0 <= self.cursor_idx < len(nav):
            return nav[self.cursor_idx]
        return None

    def _has_changes(self) -> bool:
        day = self._day()
        return has_changes(
            self._timed_tasks, self._untimed_tasks,
            day.original_lines, self._new_tasks,
            day.deleted_tasks, day.original_bodies,
        )

    def _do_save(self) -> None:
        day = self._day()
        save(
            day.file_path,
            self._directory,
            self._timed_tasks,
            self._untimed_tasks,
            day.original_lines,
            self._new_tasks,
            day.deleted_tasks,
            day.original_bodies,
        )
        self._planner.reload_day_by_key(self._day_key)
        nav = self._navigable()
        self.cursor_idx = min(self.cursor_idx, max(len(nav) - 1, 0))

    # ── Navigation ────────────────────────────────────────────────────────────

    def action_cursor_down(self) -> None:
        nav = self._navigable()
        if nav:
            self.cursor_idx = min(self.cursor_idx + 1, len(nav) - 1)

    def action_cursor_up(self) -> None:
        self.cursor_idx = max(self.cursor_idx - 1, 0)

    # ── Time manipulation ─────────────────────────────────────────────────────

    def _shift_selected(self, direction: int) -> None:
        task = self._selected()
        if task is None or task.parent is not None:
            return
        day = self._day()
        if task.time is None:
            task.time = TaskTime(start="12:00")
        else:
            start_m = get_minutes(task.time.start)
            if task.time.end:
                end_m = get_minutes(task.time.end)
                duration = end_m - start_m
                new_start = max(0, min(start_m + direction * _STEP_M, 24 * 60 - duration))
                task.time = TaskTime(
                    start=minutes_to_time(new_start),
                    end=minutes_to_time(new_start + duration),
                )
            else:
                new_start = max(0, min(start_m + direction * _STEP_M, 23 * 60 + 45))
                task.time = TaskTime(start=minutes_to_time(new_start))
        nav = self._navigable()
        self.cursor_idx = next(
            (i for i, t in enumerate(nav) if t is task), self.cursor_idx
        )
        self.refresh()

    def action_shift_left(self)  -> None: self._shift_selected(-1)
    def action_shift_right(self) -> None: self._shift_selected(1)

    def action_shrink_end(self) -> None:
        task = self._selected()
        if task is None or task.parent is not None or task.time is None:
            return
        if task.time.end:
            start_m = get_minutes(task.time.start)
            new_end = get_minutes(task.time.end) - _STEP_M
            if new_end > start_m:
                task.time = TaskTime(start=task.time.start, end=minutes_to_time(new_end))
            else:
                task.time = TaskTime(start=task.time.start)
            self.refresh()

    def action_extend_end(self) -> None:
        task = self._selected()
        if task is None or task.parent is not None or task.time is None:
            return
        if task.time.end:
            new_end = min(get_minutes(task.time.end) + _STEP_M, 24 * 60)
        else:
            new_end = min(get_minutes(task.time.start) + _STEP_M, 24 * 60)
        task.time = TaskTime(start=task.time.start, end=minutes_to_time(new_end))
        self.refresh()

    def action_remove_time(self) -> None:
        task = self._selected()
        if task is None or task.parent is not None:
            return
        if task.time:
            task.time = None
            nav = self._navigable()
            self.cursor_idx = min(self.cursor_idx, max(len(nav) - 1, 0))
            self.refresh()

    # ── Status ────────────────────────────────────────────────────────────────

    def _set_status(self, status: str) -> None:
        task = self._selected()
        if task:
            task.status = status
            self.refresh()

    def action_status_todo(self)        -> None: self._set_status("todo")
    def action_status_in_progress(self) -> None: self._set_status("in progress")
    def action_status_started(self)     -> None: self._set_status("started")
    def action_status_done(self)        -> None: self._set_status("done")
    def action_status_failed(self)      -> None: self._set_status("failed")

    # ── Form actions ──────────────────────────────────────────────────────────

    def action_edit_task(self) -> None:
        task = self._selected()
        if task is None:
            return
        from .task_form_screen import TaskFormScreen, TaskFormResult

        def on_result(result: TaskFormResult | None) -> None:
            if result is None:
                return
            task.title = result.title
            task.status = result.status
            task.body = result.body
            if result.time_start:
                task.time = TaskTime(
                    start=result.time_start,
                    end=result.time_end if result.time_end else None,
                )
            else:
                task.time = None
            fix_parent_refs(task.children, task)
            nav = self._navigable()
            self.cursor_idx = next(
                (i for i, t in enumerate(nav) if t is task),
                min(self.cursor_idx, max(len(nav) - 1, 0)),
            )
            self.refresh()

        self.app.push_screen(TaskFormScreen(task), on_result)

    def action_new_task(self) -> None:
        from .task_form_screen import TaskFormScreen, TaskFormResult

        def on_result(result: TaskFormResult | None) -> None:
            if result is None:
                return
            time = None
            if result.time_start:
                time = TaskTime(
                    start=result.time_start,
                    end=result.time_end if result.time_end else None,
                )
            new_task = Task(
                title=result.title,
                status=result.status,
                time=time,
                line_number=-1,
                indent="",
                body=result.body,
                children=result.subtasks,
            )
            fix_parent_refs(new_task.children, new_task)
            self._day().task_list.append(new_task)
            nav = self._navigable()
            self.cursor_idx = next(
                (i for i, t in enumerate(nav) if t is new_task), len(nav) - 1
            )
            self.refresh()

        self.app.push_screen(TaskFormScreen(), on_result)

    def action_delete_task(self) -> None:
        task = self._selected()
        if task is None:
            return
        day = self._day()
        if task.parent is None:
            day.task_list.remove(task)
            if task.line_number > 0:
                day.deleted_tasks.append(task)
        else:
            task.parent.children.remove(task)
            if task.line_number > 0:
                day.deleted_tasks.append(task)
        nav = self._navigable()
        self.cursor_idx = min(self.cursor_idx, max(len(nav) - 1, 0))
        self.refresh()

    # ── Save / quit ───────────────────────────────────────────────────────────

    def action_save(self) -> None:
        if not self._has_changes():
            return
        from .save_dialog import SaveDialog

        def on_confirm(save_it: bool) -> None:
            if save_it:
                self._do_save()
                self.refresh()

        self.app.push_screen(SaveDialog(), on_confirm)

    def action_quit(self) -> None:
        def _close() -> None:
            if len(self.app.screen_stack) > 2:
                self.app.screen.dismiss(None)
            else:
                self.app.exit()

        if self._has_changes():
            from .save_dialog import SaveDialog

            def on_save(save_it: bool) -> None:
                if save_it:
                    self._do_save()
                _close()

            self.app.push_screen(SaveDialog(), on_save)
        else:
            _close()


class DayScreen(Screen):
    def __init__(
        self,
        planner: PlannerState,
        directory: str,
        file_path: str,
        date: datetime.date | None = None,
    ):
        super().__init__()
        self._planner = planner
        self._directory = directory
        self._file_path = file_path
        self._date = date

    def compose(self) -> ComposeResult:
        yield DayGrid(self._planner, self._directory, self._file_path, self._date)

    def on_mount(self) -> None:
        self.query_one(DayGrid).focus()
