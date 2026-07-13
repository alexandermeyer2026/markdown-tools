import datetime
import os
import textwrap

from rich.console import Group
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.reactive import reactive
from textual.screen import Screen
from textual.widget import Widget

from models import Task, TaskTime, get_minutes, minutes_to_time
from models.file import RawLine, TaskBlock, write_nodes
from os_utils import BackupManager
from tools.journal_tools.rendering import (
    STATUS_ICONS, STATUS_STYLES, append_priority, get_time_slot, scale_lines,
)
from .state import DayCache, PlannerState
from .utils import flatten_tasks, next_priority


_STEP = 0.25          # hours per slot (15 min)
_STEP_M = int(_STEP * 60)
_MARGIN = "  "


def save(day: DayCache, directory: str) -> None:
    if not day.has_changes:
        return
    if day.file_path is None:
        raise ValueError("cannot save a day with no file path")
    if os.path.exists(day.file_path):
        BackupManager.backup(day.file_path, directory)
    write_nodes(day.file_path, day.nodes)
    day.mark_saved()


class DayGrid(Widget, can_focus=True):
    DEFAULT_CSS = """
    DayGrid {
        width: 1fr;
        height: 1fr;
    }
    """

    BINDINGS = [
        Binding("j",     "cursor_down",   show=False),
        Binding("down",  "cursor_down",   show=False),
        Binding("k",     "cursor_up",     show=False),
        Binding("up",    "cursor_up",     show=False),
        Binding("h",     "shift_left",    show=False),
        Binding("left",  "shift_left",    show=False),
        Binding("l",     "shift_right",   show=False),
        Binding("right", "shift_right",   show=False),
        Binding("H",          "shrink_end",   show=False),
        Binding("shift+left", "shrink_end",   show=False),
        Binding("L",          "extend_end",   show=False),
        Binding("shift+right","extend_end",   show=False),
        Binding("r",     "remove_time",   show=False),
        Binding("t",      "status_todo",        show=False),
        Binding("i",      "status_in_progress", show=False),
        Binding("s",      "status_started",     show=False),
        Binding("d",      "status_done",        show=False),
        Binding("f",      "status_failed",      show=False),
        Binding("exclamation_mark", "cycle_priority", show=False),
        Binding("tab",        "tab_task",       show=False),
        Binding("shift+tab",  "shift_tab_task", show=False),
        Binding("J",         "move_down",       show=False),
        Binding("shift+down","move_down",       show=False),
        Binding("K",         "move_up",         show=False),
        Binding("shift+up",  "move_up",         show=False),
        Binding("enter",  "edit_task",          show=False),
        Binding("n",      "new_task",           show=False),
        Binding("backspace", "delete_task",     show=False),
        Binding("ctrl+r", "reload",              show=False),
        Binding("ctrl+s", "save",               show=False),
        Binding("ctrl+c","quit",          show=False),
        Binding("space",  "toggle_select", show=False),
        Binding("escape", "escape",        show=False),
        Binding("c",      "toggle_collapse", show=False),
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
        self._multiselect: list[Task] = []
        self._collapsed = False

    def on_mount(self) -> None:
        self._day_key, _ = self._planner.load_file(self._file_path, self._date)
        self._day().checkpoint()

    # ── State accessors ───────────────────────────────────────────────────────

    def _day(self) -> DayCache:
        assert self._day_key is not None
        return self._planner.days[self._day_key]

    @property
    def _timed_tasks(self) -> list:
        return sorted(
            [b for b in self._day().task_list if b.task.time],
            key=lambda b: get_minutes(b.task.time.start),
        )

    @property
    def _untimed_tasks(self) -> list:
        return [b for b in self._day().task_list if not b.task.time]

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

            for block in timed:
                task = block.task
                start_slot = get_time_slot(get_minutes(task.time.start), _STEP)
                end_slot = start_slot
                if task.time.end:
                    end_slot = get_time_slot(get_minutes(task.time.end) - 1, _STEP)
                bar_width = max(end_slot - start_slot + 1, 1)
                icon_col = start_slot + bar_width + len(task.time.to_str()) + 2
                task_row = self._timed_task_row(task, selected)
                if now_slot is not None:
                    task_row = self._insert_now_col(task_row, now_col)
                lines.append(task_row)
                if not self._collapsed:
                    task_body = self._body_rows(block, time_offset=icon_col)
                    task_subs = self._subtask_rows(block, selected, time_offset=icon_col)
                    if now_slot is not None:
                        task_body = [self._insert_now_col(l, now_col) for l in task_body]
                        task_subs = [self._insert_now_col(l, now_col) for l in task_subs]
                    lines.extend(task_body)
                    lines.extend(task_subs)
        else:
            lines.append(Text.assemble(_MARGIN, ("No timed tasks yet", "bright_black")))

        if untimed:
            lines.append(Text(""))
            lines.append(
                Text.assemble(_MARGIN, ("── Unscheduled " + "─" * 50, "bright_black"))
            )
            for block in untimed:
                task = block.task
                lines.append(self._untimed_task_row(task, selected))
                if not self._collapsed:
                    lines.extend(self._body_rows(block))
                    lines.extend(self._subtask_rows(block, selected))

        if not timed and not untimed:
            lines.append(Text(""))
            lines.append(
                Text.assemble(_MARGIN, ("No tasks. Press n to add one.", "bright_black"))
            )

        lines.append(Text(""))
        c_hint = "[c] expand" if self._collapsed else "[c] collapse"
        hints = (
            f"[j/k] move  [space] select  [h/l] shift  [H/L] end time  [r] remove time  "
            f"[n] new  [Enter] edit  [t/i/s/d/f] status  [!] priority  {c_hint}  [ctrl+s] save  [ctrl+r] reload  [Esc] back"
        )
        lines.append(Text(_MARGIN + hints, style="bright_black"))

        w = self.size.width
        return Group(*[line[:w] for line in lines])

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

        in_multi = self._in_sel(task)
        if is_sel:
            t = Text(" " * offset + "> ")
        else:
            t = Text(_MARGIN + " " * offset)
        t.append("█" * bar_width, style=style)
        t.append(f" {task.time.to_str()} ")
        t.append(icon, style=style)
        t.append(" ")
        append_priority(t, task.priority)
        t.append(task.title[:title_max], style="bold reverse" if (is_sel or in_multi) else "bold")
        return t

    def _untimed_task_row(self, task: Task, selected: Task | None) -> Text:
        icon = STATUS_ICONS.get(task.status, "?")
        style = STATUS_STYLES.get(task.status, "bright_black")
        is_sel = task is selected
        in_multi = self._in_sel(task)
        title_max = max(self.size.width - 4, 0)
        t = Text("> " if is_sel else "  ")
        t.append(icon, style=style)
        t.append(" ")
        append_priority(t, task.priority)
        t.append(task.title[:title_max], style="bold reverse" if (is_sel or in_multi) else "bold")
        return t

    def _body_rows(self, block: TaskBlock, depth: int = 0, time_offset: int = 0) -> list[Text]:
        body_lines = [n.raw.rstrip('\n') for n in block.nodes if isinstance(n, RawLine)]
        if not body_lines:
            return []
        body_text = textwrap.dedent('\n'.join(body_lines)).strip()
        if not body_text:
            return []
        rows = []
        prefix = " " * time_offset + "  " * (depth + 1)
        for line in body_text.split('\n'):
            stripped = line.strip()
            if stripped:
                t = Text(_MARGIN + prefix)
                t.append(stripped, style="bright_black italic")
                rows.append(t)
        return rows

    def _subtask_rows(self, block: TaskBlock, selected: Task | None, depth: int = 1, time_offset: int = 0) -> list[Text]:
        rows: list[Text] = []
        for child_block in [n for n in block.nodes if isinstance(n, TaskBlock)]:
            child = child_block.task
            icon = STATUS_ICONS.get(child.status, "?")
            leading = " " * time_offset + "  " * depth
            title_max = max(self.size.width - len(leading) - 4, 0)
            t = Text(_MARGIN)
            child_in_multi = self._in_sel(child)
            if child is selected:
                t.append(leading[:-2] if len(leading) >= 2 else leading)
                t.append("> ")
                t.append(icon)
                t.append(" ")
                append_priority(t, child.priority)
                t.append(child.title[:title_max], style="reverse")
            elif child_in_multi:
                t.append(leading)
                t.append(icon, style=STATUS_STYLES.get(child.status, "bright_black"))
                t.append(" ")
                append_priority(t, child.priority)
                t.append(child.title[:title_max], style="reverse")
            else:
                t.append(leading)
                t.append(icon, style=STATUS_STYLES.get(child.status, "bright_black"))
                t.append(" ")
                append_priority(t, child.priority)
                t.append(child.title[:title_max])
            rows.append(t)
            rows.extend(self._body_rows(child_block, depth, time_offset))
            rows.extend(self._subtask_rows(child_block, selected, depth + 1, time_offset))
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
        blocks = self._timed_tasks + self._untimed_tasks
        if self._collapsed:
            return [b.task for b in blocks]
        return flatten_tasks(blocks)

    def _selected(self) -> Task | None:
        nav = self._navigable()
        if nav and 0 <= self.cursor_idx < len(nav):
            return nav[self.cursor_idx]
        return None

    def _has_changes(self) -> bool:
        return self._day().has_changes

    def _in_sel(self, task: Task) -> bool:
        return any(t is task for t in self._multiselect)

    def _active_tasks(self) -> list[Task]:
        result = list(self._multiselect)
        cursor = self._selected()
        if cursor and not self._in_sel(cursor):
            result.append(cursor)
        return result

    # ── Multiselect ───────────────────────────────────────────────────────────

    def action_toggle_select(self) -> None:
        task = self._selected()
        if task is None:
            return
        if self._in_sel(task):
            self._multiselect = [t for t in self._multiselect if t is not task]
        else:
            self._multiselect.append(task)
        self.refresh()

    def action_clear_select(self) -> None:
        if self._multiselect:
            self._multiselect = []
            self.refresh()

    def action_escape(self) -> None:
        if self._multiselect:
            self.action_clear_select()
        else:
            self.action_quit()

    def action_toggle_collapse(self) -> None:
        self._collapsed = not self._collapsed
        nav = self._navigable()
        self.cursor_idx = min(self.cursor_idx, max(len(nav) - 1, 0))
        self.refresh()

    def _do_save(self) -> None:
        save(self._day(), self._directory)
        self._day().update_checkpoint()
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

    def _new_time_for(self, task: Task, direction: int) -> TaskTime:
        if task.time is None:
            return TaskTime(start="12:00")
        start_m = get_minutes(task.time.start)
        if task.time.end:
            end_m = get_minutes(task.time.end)
            duration = end_m - start_m
            new_start = max(0, min(start_m + direction * _STEP_M, 24 * 60 - duration))
            return TaskTime(
                start=minutes_to_time(new_start),
                end=minutes_to_time(new_start + duration),
            )
        new_start = max(0, min(start_m + direction * _STEP_M, 23 * 60 + 45))
        return TaskTime(start=minutes_to_time(new_start))

    def _shift_selected(self, direction: int) -> None:
        tasks = [t for t in self._active_tasks() if not t.indent]
        if not tasks:
            return
        cursor = self._selected()
        day = self._day()
        for task in tasks:
            day.set_time(task, self._new_time_for(task, direction))
        if cursor:
            nav = self._navigable()
            self.cursor_idx = next(
                (i for i, t in enumerate(nav) if t is cursor), self.cursor_idx
            )
        self.refresh()

    def action_shift_left(self)  -> None: self._shift_selected(-1)
    def action_shift_right(self) -> None: self._shift_selected(1)

    def action_shrink_end(self) -> None:
        task = self._selected()
        if task is None or task.indent or task.time is None or not task.time.end:
            return
        start_m = get_minutes(task.time.start)
        new_end = get_minutes(task.time.end) - _STEP_M
        if new_end > start_m:
            new_time = TaskTime(start=task.time.start, end=minutes_to_time(new_end))
        else:
            new_time = TaskTime(start=task.time.start)
        self._day().set_time(task, new_time)
        self.refresh()

    def action_extend_end(self) -> None:
        task = self._selected()
        if task is None or task.indent or task.time is None:
            return
        if task.time.end:
            new_end = min(get_minutes(task.time.end) + _STEP_M, 24 * 60)
        else:
            new_end = min(get_minutes(task.time.start) + _STEP_M, 24 * 60)
        new_time = TaskTime(start=task.time.start, end=minutes_to_time(new_end))
        self._day().set_time(task, new_time)
        self.refresh()

    def action_remove_time(self) -> None:
        task = self._selected()
        if task is None or task.indent or not task.time:
            return
        self._day().set_time(task, None)
        nav = self._navigable()
        self.cursor_idx = min(self.cursor_idx, max(len(nav) - 1, 0))
        self.refresh()

    # ── Status ────────────────────────────────────────────────────────────────

    def _set_status(self, status: str) -> None:
        day = self._day()
        for task in self._active_tasks():
            day.set_status(task, status)
        self.refresh()

    def action_status_todo(self)        -> None: self._set_status("todo")
    def action_status_in_progress(self) -> None: self._set_status("in progress")
    def action_status_started(self)     -> None: self._set_status("started")
    def action_status_done(self)        -> None: self._set_status("done")
    def action_status_failed(self)      -> None: self._set_status("failed")

    def action_cycle_priority(self) -> None:
        day = self._day()
        for task in self._active_tasks():
            day.set_priority(task, next_priority(task.priority))
        self.refresh()

    # ── Hierarchy / reorder ───────────────────────────────────────────────────

    def _move_hierarchy(self, fn) -> None:
        task = self._selected()
        if task is None:
            return
        if fn(task):
            nav = self._navigable()
            self.cursor_idx = next(
                (i for i, t in enumerate(nav) if t is task), self.cursor_idx
            )
            self.refresh()

    def action_tab_task(self) -> None:
        self._move_hierarchy(self._day().tab_task_block)

    def action_shift_tab_task(self) -> None:
        self._move_hierarchy(self._day().shift_tab_task_block)

    def action_move_down(self) -> None:
        self._move_hierarchy(lambda t: self._day().reorder_block(t, 1))

    def action_move_up(self) -> None:
        self._move_hierarchy(lambda t: self._day().reorder_block(t, -1))

    # ── Form actions ──────────────────────────────────────────────────────────

    def action_edit_task(self) -> None:
        task = self._selected()
        if task is None:
            return
        from .task_form_screen import TaskFormScreen, TaskFormResult
        day = self._day()
        block = day.find_block(task)
        if block is None:
            return

        def on_result(result: TaskFormResult | None) -> None:
            if result is None:
                return
            time = None
            if result.time_start:
                time = TaskTime(
                    start=result.time_start,
                    end=result.time_end if result.time_end else None,
                )
            day.update_task(task, result.title, result.status, time, result.body, result.subtasks)
            nav = self._navigable()
            self.cursor_idx = next(
                (i for i, t in enumerate(nav) if t is task),
                min(self.cursor_idx, max(len(nav) - 1, 0)),
            )
            self.refresh()

        self.app.push_screen(TaskFormScreen(block), on_result)

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
            )
            day = self._day()
            day.insert_task(new_task, result.body, result.subtasks)
            nav = self._navigable()
            self.cursor_idx = next(
                (i for i, t in enumerate(nav) if t is new_task), len(nav) - 1
            )
            self.refresh()

        self.app.push_screen(TaskFormScreen(), on_result)

    def action_delete_task(self) -> None:
        tasks = list(self._active_tasks())
        if not tasks:
            return

        def on_confirm(confirmed: bool) -> None:
            if not confirmed:
                return
            day = self._day()
            for task in tasks:
                block = day.find_block(task)
                if block:
                    day.remove_block(block)
            self._multiselect = []
            nav = self._navigable()
            self.cursor_idx = min(self.cursor_idx, max(len(nav) - 1, 0))
            self.refresh()

        from .save_dialog import SaveDialog
        self.app.push_screen(SaveDialog("Delete task?"), on_confirm)

    # ── Save / quit ───────────────────────────────────────────────────────────

    def action_reload(self) -> None:
        self._planner.reload_day_by_key(self._day_key)
        self._day().checkpoint()
        nav = self._navigable()
        self.cursor_idx = min(self.cursor_idx, max(len(nav) - 1, 0))
        self.refresh()

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
                else:
                    self._day().restore_checkpoint()
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
