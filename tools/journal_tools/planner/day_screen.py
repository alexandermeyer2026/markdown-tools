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
from parser import TaskParser
from tools.journal_tools.rendering import (
    STATUS_ICONS, STATUS_STYLES, get_time_slot, scale_lines,
)
from .daily import has_changes, save
from .utils import flatten_tasks

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
        directory: str,
        file_path: str,
        date: datetime.date | None,
    ):
        super().__init__()
        self._directory = directory
        self._file_path = file_path
        self._date = date
        self._timed_tasks: list[Task] = []
        self._untimed_tasks: list[Task] = []
        self._new_tasks: list[Task] = []
        self._deleted_tasks: list[Task] = []
        self._original_lines: dict[int, str] = {}

    def on_mount(self) -> None:
        tasks = TaskParser.parse_file(self._file_path)
        self._timed_tasks = sorted(
            [t for t in tasks if t.time and t.parent is None],
            key=lambda t: get_minutes(t.time.start),
        )
        self._untimed_tasks = [t for t in tasks if not t.time and t.parent is None]
        self._original_lines = {
            t.line_number: t.to_line() for t in tasks if t.line_number > 0
        }

    # ── Rendering ─────────────────────────────────────────────────────────────

    def render(self) -> Group:
        navigable = flatten_tasks(self._timed_tasks + self._untimed_tasks)
        selected = navigable[self.cursor_idx] if navigable else None

        rel_path = os.path.relpath(self._file_path, self._directory)
        has_chg = has_changes(
            self._timed_tasks, self._untimed_tasks, self._original_lines, self._new_tasks
        )
        marker = " *" if has_chg else ""

        lines: list[Text] = [
            Text.assemble(_MARGIN, (f"Planning: {rel_path}{marker}", "bold")),
            Text(""),
        ]

        if self._timed_tasks:
            now_slot = None
            if self._date and self._date == datetime.date.today():
                now_m = datetime.datetime.now().hour * 60 + datetime.datetime.now().minute
                now_slot = get_time_slot(now_m, _STEP)

            hours_str, scale_str = scale_lines(_STEP, 0, now_slot)
            hours_text = Text(_MARGIN + hours_str)
            scale_text = Text(_MARGIN)
            for i, ch in enumerate(scale_str):
                if now_slot is not None and i == now_slot:
                    scale_text.append(ch, style="bold yellow")
                else:
                    scale_text.append(ch, style="bright_black")
            lines.append(hours_text)
            lines.append(scale_text)

            for task in self._timed_tasks:
                start_slot = get_time_slot(get_minutes(task.time.start), _STEP)
                end_slot = start_slot
                if task.time.end:
                    end_slot = get_time_slot(get_minutes(task.time.end) - 1, _STEP)
                bar_width = max(end_slot - start_slot + 1, 1)
                icon_col = start_slot + bar_width + len(task.time.to_str()) + 2
                lines.append(self._timed_task_row(task, selected))
                lines.extend(self._subtask_rows(task, selected, time_offset=icon_col))
        else:
            lines.append(Text.assemble(_MARGIN, ("No timed tasks yet", "bright_black")))

        if self._untimed_tasks:
            lines.append(Text(""))
            lines.append(
                Text.assemble(_MARGIN, ("── Unscheduled " + "─" * 50, "bright_black"))
            )
            for task in self._untimed_tasks:
                lines.append(self._untimed_task_row(task, selected))
                lines.extend(self._subtask_rows(task, selected))

        if not self._timed_tasks and not self._untimed_tasks:
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

        t = Text(_MARGIN)
        if is_sel:
            t.append(" " * max(offset - 2, 0))
            t.append("> ")
        else:
            t.append(" " * offset)
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
            rows.extend(self._subtask_rows(child, selected, depth + 1, time_offset))
        return rows

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _navigable(self) -> list[Task]:
        return flatten_tasks(self._timed_tasks + self._untimed_tasks)

    def _selected(self) -> Task | None:
        nav = self._navigable()
        if nav and 0 <= self.cursor_idx < len(nav):
            return nav[self.cursor_idx]
        return None

    def _has_changes(self) -> bool:
        return has_changes(
            self._timed_tasks, self._untimed_tasks, self._original_lines,
            self._new_tasks, self._deleted_tasks,
        )

    def _do_save(self) -> None:
        save(
            self._file_path,
            self._directory,
            self._timed_tasks,
            self._untimed_tasks,
            self._original_lines,
            self._new_tasks,
            self._deleted_tasks,
        )

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
        if task.time is None:
            task.time = TaskTime(start="12:00")
            self._untimed_tasks.remove(task)
            self._timed_tasks.append(task)
            self._timed_tasks.sort(key=lambda t: get_minutes(t.time.start))
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
            self._timed_tasks.sort(key=lambda t: get_minutes(t.time.start))
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
        if task.time and task in self._timed_tasks:
            task.time = None
            self._timed_tasks.remove(task)
            self._untimed_tasks.insert(0, task)
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
            had_time = task.time is not None
            if result.time_start:
                task.time = TaskTime(
                    start=result.time_start,
                    end=result.time_end if result.time_end else None,
                )
                if not had_time and task in self._untimed_tasks:
                    self._untimed_tasks.remove(task)
                    self._timed_tasks.append(task)
                self._timed_tasks.sort(key=lambda t: get_minutes(t.time.start))
            else:
                if task.time and task in self._timed_tasks:
                    self._timed_tasks.remove(task)
                    self._untimed_tasks.insert(0, task)
                task.time = None
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
            )
            if time:
                self._timed_tasks.append(new_task)
                self._timed_tasks.sort(key=lambda t: get_minutes(t.time.start))
            else:
                self._untimed_tasks.append(new_task)
            self._new_tasks.append(new_task)
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
        if task.parent is None:
            if task in self._timed_tasks:
                self._timed_tasks.remove(task)
            else:
                self._untimed_tasks.remove(task)
            if task in self._new_tasks:
                self._new_tasks.remove(task)
            elif task.line_number > 0:
                self._deleted_tasks.append(task)
        else:
            task.parent.children.remove(task)
            if task.line_number > 0:
                self._deleted_tasks.append(task)
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
        directory: str,
        file_path: str,
        date: datetime.date | None = None,
    ):
        super().__init__()
        self._directory = directory
        self._file_path = file_path
        self._date = date

    def compose(self) -> ComposeResult:
        yield DayGrid(self._directory, self._file_path, self._date)

    def on_mount(self) -> None:
        self.query_one(DayGrid).focus()
