import datetime
import os

from rich.console import Group
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.reactive import reactive
from textual.screen import Screen
from textual.widget import Widget

from models import Task, TaskTime
from tools.journal_tools.rendering import STATUS_ICONS, STATUS_STYLES
from .state import PlannerState, WeekState
from .utils import week_expanded, root_task, fix_parent_refs
from .weekly import (
    DAY_NAMES,
    cache_has_changes,
    save_cache,
    shift_task,
)

_MARGIN = "  "


class WeekGrid(Widget, can_focus=True):
    DEFAULT_CSS = """
    WeekGrid {
        width: 1fr;
        height: 1fr;
    }
    """

    BINDINGS = [
        Binding("j",     "cursor_down",       show=False),
        Binding("k",     "cursor_up",         show=False),
        Binding("h",     "cursor_left",       show=False),
        Binding("l",     "cursor_right",      show=False),
        Binding("H",     "move_left",         show=False),
        Binding("L",     "move_right",        show=False),
        Binding(">",     "carry_subtasks",    show=False),
        Binding("t",      "status_todo",        show=False),
        Binding("i",      "status_in_progress", show=False),
        Binding("s",      "status_started",     show=False),
        Binding("d",      "status_done",        show=False),
        Binding("f",      "status_failed",      show=False),
        Binding("enter",  "open_or_edit",       show=False),
        Binding("n",      "new_task",           show=False),
        Binding("D",      "delete_task",        show=False),
        Binding("ctrl+s", "save",               show=False),
        Binding("q",     "quit",              show=False),
        Binding("ctrl+c","quit",              show=False),
    ]

    cursor_col: reactive[int] = reactive(0, repaint=True)
    cursor_row: reactive[int] = reactive(0, repaint=True)

    def __init__(self, planner: PlannerState, directory: str, week_offset: int = 0):
        super().__init__()
        self._planner = planner
        self._directory = directory
        self._week_offset = week_offset
        self._state: WeekState | None = None

    def on_mount(self) -> None:
        self._load_week()
        self.cursor_col = datetime.date.today().weekday()

    def _load_week(self) -> None:
        today = datetime.date.today()
        monday = (
            today
            - datetime.timedelta(days=today.weekday())
            + datetime.timedelta(weeks=self._week_offset)
        )
        week_days = [monday + datetime.timedelta(days=i) for i in range(7)]
        for day in week_days:
            self._planner.load_day(day)
        self._state = WeekState(week_days=week_days, planner=self._planner)
        self.refresh()

    # ── Rendering ─────────────────────────────────────────────────────────────

    def render(self) -> Group:
        if self._state is None:
            return Group(Text("Loading…"))

        state = self._state
        today = datetime.date.today()
        col_width = max((self.size.width - 2) // 7, 10)

        has_chg = cache_has_changes(self._planner.days)
        marker = " *" if has_chg else ""
        monday, sunday = state.week_days[0], state.week_days[-1]

        lines: list[Text] = [
            Text.assemble(
                _MARGIN,
                (f"Week {monday.strftime('%b %d')} – {sunday.strftime('%b %d, %Y')}{marker}", "bold"),
            ),
            Text(""),
        ]

        # Day-name header row
        header = Text(_MARGIN)
        for i, day in enumerate(state.week_days):
            label = f"{DAY_NAMES[i]} {day.strftime('%m/%d')}"
            padded = label.ljust(col_width)[:col_width]
            if self.cursor_row == -1 and i == self.cursor_col:
                header.append(padded, style="reverse")
            elif day == today:
                header.append(padded, style="bold")
            else:
                header.append(padded)
        lines.append(header)
        lines.append(Text(_MARGIN + ("─" * (col_width - 1) + " ") * 7))

        # Task rows
        expanded = [week_expanded(state.day(i).task_list) for i in range(7)]
        max_rows = max((len(e) for e in expanded), default=0)
        max_rows = max(max_rows, 1)

        for row in range(max_rows):
            line = Text(_MARGIN)
            for col_idx in range(7):
                exp = expanded[col_idx]
                is_sel = col_idx == self.cursor_col and row == self.cursor_row
                if row < len(exp):
                    line.append_text(self._week_cell(exp[row], col_width, is_sel))
                elif is_sel:
                    line.append(" " * col_width, style="reverse")
                else:
                    line.append(" " * col_width)
            lines.append(line)

        lines.append(Text(""))
        hints = (
            "[h/j/k/l] navigate  [H/L] move  [>] carry  "
            "[t/i/s/d/f] status  [Enter] open/edit  [n] new  [ctrl+s] save  [q] quit"
        )
        lines.append(Text(_MARGIN + hints, style="bright_black"))

        return Group(*lines)

    def _week_cell(self, task: Task | None, col_width: int, is_selected: bool) -> Text:
        if task is None:
            t = Text(" " * col_width)
            if is_selected:
                t.stylize("reverse")
            return t

        icon = STATUS_ICONS.get(task.status, "?")
        style = STATUS_STYLES.get(task.status, "bright_black")

        if task.parent is not None:
            depth = 0
            p = task.parent
            while p is not None:
                depth += 1
                p = p.parent
            indent = "  " * depth
            title_max = max(col_width - 4 - depth * 2, 1)
            title_str = task.title[:title_max].ljust(title_max)
            t = Text("  ")
            if is_selected:
                t.append(indent[:-2] if len(indent) >= 2 else "")
                t.append("> ")
                t.append(icon)
            else:
                t.append(indent, style="bright_black")
                t.append(icon, style="bright_black")
            t.append(" ")
            t.append(title_str, style="reverse" if is_selected else "bright_black")
            return t

        title_max = col_width - 4
        title_str = task.title[:title_max].ljust(title_max)
        t = Text("> " if is_selected else "  ")
        t.append(icon, style=style)
        t.append(" ")
        t.append(title_str, style="reverse" if is_selected else "")
        return t

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _selected_task(self) -> Task | None:
        if self._state is None or self.cursor_row < 0:
            return None
        exp = week_expanded(self._state.day(self.cursor_col).task_list)
        if self.cursor_row < len(exp):
            return exp[self.cursor_row]
        return None

    def _selected_day(self) -> datetime.date:
        assert self._state is not None
        return self._state.week_days[self.cursor_col]

    def _clamp_row(self) -> None:
        if self._state is None:
            return
        exp = week_expanded(self._state.day(self.cursor_col).task_list)
        if self.cursor_row >= len(exp):
            self.cursor_row = max(len(exp) - 1, -1)

    # ── Navigation actions ────────────────────────────────────────────────────

    def action_cursor_down(self) -> None:
        if self._state is None:
            return
        if self.cursor_row == -1:
            self.cursor_row = 0
        else:
            exp = week_expanded(self._state.day(self.cursor_col).task_list)
            if exp:
                self.cursor_row = min(self.cursor_row + 1, len(exp) - 1)

    def action_cursor_up(self) -> None:
        self.cursor_row = max(self.cursor_row - 1, -1)

    def action_cursor_left(self) -> None:
        if self._state is None:
            return
        if self.cursor_col == 0:
            self._week_offset -= 1
            self._load_week()
            self.cursor_col = 6
        else:
            self.cursor_col -= 1
            self._clamp_row()

    def action_cursor_right(self) -> None:
        if self._state is None:
            return
        if self.cursor_col == 6:
            self._week_offset += 1
            self._load_week()
            self.cursor_col = 0
        else:
            self.cursor_col += 1
            self._clamp_row()

    # ── Task mutation actions ─────────────────────────────────────────────────

    def _set_status(self, status: str) -> None:
        task = self._selected_task()
        if task:
            task.status = status
            self.refresh()

    def action_status_todo(self)        -> None: self._set_status("todo")
    def action_status_in_progress(self) -> None: self._set_status("in progress")
    def action_status_started(self)     -> None: self._set_status("started")
    def action_status_done(self)        -> None: self._set_status("done")
    def action_status_failed(self)      -> None: self._set_status("failed")

    def action_move_left(self) -> None:
        if self._state is None or self.cursor_row < 0:
            return
        new_col, new_row, week_exit = shift_task(
            self._state, self.cursor_col, self.cursor_row, -1
        )
        if week_exit:
            self._week_offset += week_exit
            self._load_week()
            self.cursor_col = 6 if week_exit == -1 else 0
            self.cursor_row = new_row
        else:
            self.cursor_col = new_col
            self.cursor_row = new_row

    def action_move_right(self) -> None:
        if self._state is None or self.cursor_row < 0:
            return
        new_col, new_row, week_exit = shift_task(
            self._state, self.cursor_col, self.cursor_row, 1
        )
        if week_exit:
            self._week_offset += week_exit
            self._load_week()
            self.cursor_col = 6 if week_exit == -1 else 0
            self.cursor_row = new_row
        else:
            self.cursor_col = new_col
            self.cursor_row = new_row

    def action_carry_subtasks(self) -> None:
        if self._state is None or self.cursor_row < 0:
            return
        exp = week_expanded(self._state.day(self.cursor_col).task_list)
        if self.cursor_row >= len(exp):
            return
        task = exp[self.cursor_row]
        if task.parent is not None:
            return
        unfinished = [c for c in task.children if c.status not in ("done", "failed", "started")]
        if not unfinished:
            return
        task.children = [c for c in task.children if c.status in ("done", "failed", "started")]
        self._state.day(self.cursor_col).moved_subtasks.extend(unfinished)
        tomorrow = self._state.week_days[self.cursor_col] + datetime.timedelta(days=1)
        self._planner.load_day(tomorrow)
        new_task = Task(
            title=task.title,
            status="todo",
            time=None,
            line_number=-1,
            indent="",
            children=list(unfinished),
        )
        for child in unfinished:
            child.parent = new_task
        self._planner.days[tomorrow.isoformat()].task_list.append(new_task)
        self.refresh()

    def action_delete_task(self) -> None:
        task = self._selected_task()
        if task is None:
            return
        day_key = self._selected_day().isoformat()
        day_cache = self._planner.days[day_key]
        if task.parent is None:
            day_cache.task_list.remove(task)
        else:
            task.parent.children.remove(task)
        if task.line_number > 0:
            day_cache.deleted_tasks.append(task)
        self._clamp_row()
        self.refresh()

    # ── Screen-push actions ───────────────────────────────────────────────────

    def action_open_or_edit(self) -> None:
        if self._state is None:
            return
        if self.cursor_row == -1:
            self._open_day()
        else:
            task = self._selected_task()
            if task:
                self._edit_task(task)

    def _open_day(self) -> None:
        from .day_screen import DayScreen

        assert self._state is not None
        day = self._selected_day()
        day_key = day.isoformat()
        self._planner.load_day(day)

        def push_day() -> None:
            fp = self._planner.days[day_key].file_path
            if fp is None:
                fp = os.path.join(self._directory, day.strftime("%Y-%m-%d.md"))
                open(fp, "w").close()
                self._planner.reload_day_by_key(day_key, new_file_path=fp)
                fp = self._planner.days[day_key].file_path

            def on_day_closed(_result: object) -> None:
                self._planner.reload_day_by_key(day_key)
                self.refresh()

            self.app.push_screen(
                DayScreen(self._planner, self._directory, fp, day), on_day_closed
            )

        if cache_has_changes(self._planner.days):
            from .save_dialog import SaveDialog

            def on_save(save_it: bool) -> None:
                if save_it:
                    save_cache(self._planner.days, self._directory)
                push_day()

            self.app.push_screen(SaveDialog(), on_save)
        else:
            push_day()

    def _edit_task(self, task: Task) -> None:
        from .task_form_screen import TaskFormScreen, TaskFormResult

        def on_form_result(result: TaskFormResult | None) -> None:
            if result is not None:
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
            self.call_after_refresh(self.refresh)

        self.app.push_screen(TaskFormScreen(task), on_form_result)

    def action_new_task(self) -> None:
        from .task_form_screen import TaskFormScreen, TaskFormResult
        from models import Task, TaskTime

        day = self._selected_day()
        day_key = day.isoformat()
        self._planner.load_day(day)

        def on_form_result(result: TaskFormResult | None) -> None:
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
            self._planner.days[day_key].task_list.append(new_task)
            self.refresh()

        self.app.push_screen(TaskFormScreen(), on_form_result)

    def action_save(self) -> None:
        if not cache_has_changes(self._planner.days):
            return
        from .save_dialog import SaveDialog

        def on_confirm(save_it: bool) -> None:
            if save_it:
                save_cache(self._planner.days, self._directory)
                self.refresh()

        self.app.push_screen(SaveDialog(), on_confirm)

    def action_quit(self) -> None:
        if cache_has_changes(self._planner.days):
            from .save_dialog import SaveDialog

            def on_save(save: bool) -> None:
                if save:
                    save_cache(self._planner.days, self._directory)
                self.app.exit()

            self.app.push_screen(SaveDialog(), on_save)
        else:
            self.app.exit()


class WeekScreen(Screen):
    def __init__(self, planner: PlannerState, directory: str):
        super().__init__()
        self._planner = planner
        self._directory = directory

    def compose(self) -> ComposeResult:
        yield WeekGrid(self._planner, self._directory)

    def on_mount(self) -> None:
        self.query_one(WeekGrid).focus()
