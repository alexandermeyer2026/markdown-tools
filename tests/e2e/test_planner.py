import os

from textual.widgets import Input, Select, TextArea

from models.task import Task
from models.file import TaskBlock, parse, serialize, insert_task
from tools.journal_tools.planner.save_dialog import SaveDialog
from tools.journal_tools.planner.task_form_screen import TaskFormScreen

_INPUT_DIR = os.path.join(os.path.dirname(__file__), 'fixtures', 'input')
_EXPECTED_DIR = os.path.join(os.path.dirname(__file__), 'fixtures', 'expected', 'planner', 'day')


async def _save(pilot, app):
    await pilot.press("ctrl+s")
    await pilot.pause()
    if isinstance(app.screen, SaveDialog):
        await pilot.click("#yes")
        await pilot.pause()


def test_week_add_task_via_form(run_planner_scenario):
    """Weekly view: open task form, fill all fields, save form, save week."""
    async def run(pilot, app):
        await pilot.press('n')
        await pilot.pause()

        form = app.screen
        form.query_one("#title", Input).value = "standup"
        form.query_one("#status", Select).value = "in progress"
        form.query_one("#time_start", Input).value = "09:00"
        form.query_one("#time_end", Input).value = "09:30"
        form.query_one("#body", TextArea).load_text("daily sync")

        await pilot.press("ctrl+s")   # save form
        await pilot.pause()
        await _save(pilot, app)

    run_planner_scenario(run, "week/add_task_via_form", week_today="2024-01-01")


def test_week_edit_task_via_form(run_planner_scenario):
    """Weekly view: open existing task in form, change title and time end, save."""
    async def run(pilot, app):
        await pilot.press("enter")    # open edit form for first task (09:00 Morning standup)
        await pilot.pause()

        form = app.screen
        form.query_one("#title", Input).value = "Team standup"
        form.query_one("#time_end", Input).value = "09:15"

        await pilot.press("ctrl+s")   # save form
        await pilot.pause()
        await _save(pilot, app)

    run_planner_scenario(run, "week/edit_task_via_form", week_today="2024-01-02")


def test_week_edit_task_with_body_via_form(run_planner_scenario):
    """Weekly view: open task with body text in form; body must survive the round-trip."""
    async def run(pilot, app):
        await pilot.press("j")        # cursor → Present roadmap (row 1, has body text)
        await pilot.pause()
        await pilot.press("enter")    # open edit form — was crashing with NameError: RawLine
        await pilot.pause()

        form = app.screen
        form.query_one("#title", Input).value = "Present roadmap (reviewed)"

        await pilot.press("ctrl+s")   # save form
        await pilot.pause()
        await _save(pilot, app)

    run_planner_scenario(run, "week/edit_task_with_body", week_today="2024-01-05")


def test_week_multiselect_shift_right(run_planner_scenario):
    """Weekly view: select 3 tasks on Tuesday with space, shift all to Wednesday with L."""
    async def run(pilot, app):
        await pilot.press("space")    # select task 1 (Morning standup)
        await pilot.pause()
        await pilot.press("j")        # cursor → task 2
        await pilot.pause()
        await pilot.press("space")    # select task 2 (Write report)
        await pilot.pause()
        await pilot.press("j")        # cursor → task 3
        await pilot.pause()
        await pilot.press("space")    # select task 3 (Review PRs)
        await pilot.pause()
        await pilot.press("L")        # shift all selected tasks Tue → Wed
        await pilot.pause()
        await _save(pilot, app)

    run_planner_scenario(run, "week/multiselect_shift_right", week_today="2024-01-02")


def test_week_mark_tasks_done(run_planner_scenario):
    """Weekly view: walk through 3 tasks marking each a different status, save."""
    async def run(pilot, app):
        await pilot.press("d")        # mark task 1 done
        await pilot.pause()
        await pilot.press("j")        # cursor → task 2
        await pilot.pause()
        await pilot.press("f")        # mark task 2 failed
        await pilot.pause()
        await pilot.press("j")        # cursor → task 3
        await pilot.pause()
        await pilot.press("i")        # mark task 3 in progress
        await pilot.pause()
        await _save(pilot, app)

    run_planner_scenario(run, "week/mark_tasks_done", week_today="2024-01-02")


def test_week_discard_on_quit(run_planner_scenario):
    """Weekly view: make a change then quit without saving — file must stay unchanged."""
    async def run(pilot, app):
        await pilot.press("d")        # mark task 1 done (in-memory change only)
        await pilot.pause()
        await pilot.press("escape")   # quit → save dialog
        await pilot.pause()
        if isinstance(app.screen, SaveDialog):
            await pilot.click("#no")  # discard
            await pilot.pause()

    run_planner_scenario(run, "week/discard_on_quit", week_today="2024-01-02")


def test_day_shift_task_time(run_planner_scenario):
    """Day view: shift the timed task's start time forward 15 min with l, save."""
    async def run(pilot, app):
        await pilot.press("l")        # shift 09:00 Morning standup → 09:15
        await pilot.pause()
        await _save(pilot, app)

    run_planner_scenario(run, "day/shift_task_time", date="2024-01-02")


def test_week_add_task_then_move_cross_week(run_planner_scenario):
    """Weekly view: add a task on Sunday, shift it right into next week's Monday, save."""
    async def run(pilot, app):
        await pilot.press("n")        # open form on Sunday (Jan 7)
        await pilot.pause()

        app.screen.query_one("#title", Input).value = "deploy"

        await pilot.press("ctrl+s")   # save form
        await pilot.pause()
        await pilot.press("L")        # shift Sun Jan 7 → Mon Jan 8 (next week)
        await pilot.pause()
        await _save(pilot, app)

    run_planner_scenario(run, "week/add_task_then_move_cross_week", week_today="2024-01-07")


def test_week_carry_forward(run_planner_scenario):
    """Weekly view: carry unfinished subtasks to next day; finished subtask stays in source."""
    async def run(pilot, app):
        await pilot.press(">")        # carry unfinished subtasks of Sprint review → Thu Jan 4
        await pilot.pause()
        await _save(pilot, app)

    run_planner_scenario(run, "week/carry_forward", week_today="2024-01-03")


def test_week_delete_task(run_planner_scenario):
    """Weekly view: delete the first task via backspace + confirmation, save."""
    async def run(pilot, app):
        await pilot.press("backspace")   # delete Morning standup → confirmation dialog
        await pilot.pause()
        if isinstance(app.screen, SaveDialog):
            await pilot.click("#yes")
            await pilot.pause()
        await _save(pilot, app)

    run_planner_scenario(run, "week/delete_task", week_today="2024-01-02")


def test_week_carry_task_with_notes(run_planner_scenario):
    """Weekly view: carry subtask that has body text; body must survive the carry."""
    async def run(pilot, app):
        await pilot.press(">")        # carry Present roadmap (with notes) → Sat Jan 6
        await pilot.pause()
        await _save(pilot, app)

    run_planner_scenario(run, "week/carry_task_with_notes", week_today="2024-01-05")


def test_week_delete_two_tasks(run_planner_scenario):
    """Weekly view: delete two non-adjacent tasks in sequence; both must be gone on save."""
    async def run(pilot, app):
        await pilot.press("backspace")   # delete task 1 (Morning standup)
        await pilot.pause()
        if isinstance(app.screen, SaveDialog):
            await pilot.click("#yes")
            await pilot.pause()
        await pilot.press("j")           # cursor → Review PRs (now at row 1)
        await pilot.pause()
        await pilot.press("backspace")   # delete Review PRs
        await pilot.pause()
        if isinstance(app.screen, SaveDialog):
            await pilot.click("#yes")
            await pilot.pause()
        await _save(pilot, app)

    run_planner_scenario(run, "week/delete_two_tasks", week_today="2024-01-02")


def test_week_delete_then_status_change(run_planner_scenario):
    """Delete first task, then mark the newly-promoted first task done — compound mutation."""
    async def run(pilot, app):
        await pilot.press("backspace")   # delete Morning standup → confirm
        await pilot.pause()
        if isinstance(app.screen, SaveDialog):
            await pilot.click("#yes")
            await pilot.pause()
        await pilot.press("d")           # mark Write report done (now at row 0)
        await pilot.pause()
        await _save(pilot, app)

    run_planner_scenario(run, "week/delete_then_status_change", week_today="2024-01-02")


def test_week_carry_and_move(run_planner_scenario):
    """Carry unfinished subtasks to Thu, then shift the new Thu block to Fri — two-step relocation."""
    async def run(pilot, app):
        await pilot.press(">")           # carry Run demo + Write notes → Jan 4 (Thu)
        await pilot.pause()
        await pilot.press("l")           # move cursor to Jan 4 (Thu)
        await pilot.pause()
        await pilot.press("L")           # shift Sprint review Thu → Fri (Jan 5)
        await pilot.pause()
        await _save(pilot, app)

    run_planner_scenario(run, "week/carry_and_move", week_today="2024-01-03")


def test_week_delete_subtask_only(run_planner_scenario):
    """Delete a subtask; parent task and remaining subtasks must survive unchanged."""
    async def run(pilot, app):
        await pilot.press("j")           # cursor → Prepare slides (row 1, subtask)
        await pilot.pause()
        await pilot.press("backspace")   # delete Prepare slides → confirm
        await pilot.pause()
        if isinstance(app.screen, SaveDialog):
            await pilot.click("#yes")
            await pilot.pause()
        await _save(pilot, app)

    run_planner_scenario(run, "week/delete_subtask_only", week_today="2024-01-03")


def test_week_delete_subtask_then_mark_parent(run_planner_scenario):
    """Delete a subtask then mark the parent in-progress — cursor must reach parent after deletion."""
    async def run(pilot, app):
        await pilot.press("j")           # cursor → Prepare slides (row 1)
        await pilot.pause()
        await pilot.press("backspace")   # delete Prepare slides → confirm
        await pilot.pause()
        if isinstance(app.screen, SaveDialog):
            await pilot.click("#yes")
            await pilot.pause()
        await pilot.press("k")           # cursor back to Sprint review (row 0)
        await pilot.pause()
        await pilot.press("i")           # mark Sprint review in progress
        await pilot.pause()
        await _save(pilot, app)

    run_planner_scenario(run, "week/delete_subtask_then_mark_parent", week_today="2024-01-03")


def test_week_shift_enter_day_discard_return_save(run_planner_scenario):
    """Shift task to next day, enter that day view and discard, return to week — task must survive."""
    async def run(pilot, app):
        await pilot.press("L")           # shift Sprint review Wed → Thu (Jan 4)
        await pilot.pause()
        await pilot.press("k")           # cursor to column header (row -1)
        await pilot.pause()
        await pilot.press("enter")       # open Thu day view; SaveDialog fires (caches dirty)
        await pilot.pause()
        if isinstance(app.screen, SaveDialog):
            await pilot.click("#no")     # don't save yet
            await pilot.pause()
        await pilot.press("escape")      # exit day view; SaveDialog fires (day dirty)
        await pilot.pause()
        if isinstance(app.screen, SaveDialog):
            await pilot.click("#no")     # discard day view changes
            await pilot.pause()
        await _save(pilot, app)          # save from week view — Jan 4 must have the task

    run_planner_scenario(run, "week/shift_enter_day_discard_return_save", week_today="2024-01-03")


def test_week_carry_skips_started_subtasks(run_planner_scenario):
    """Carry must move only todo subtasks; started subtask stays in the source day."""
    async def run(pilot, app):
        await pilot.press(">")           # carry: Todo subtask → Jan 11; Started subtask stays
        await pilot.pause()
        await _save(pilot, app)

    run_planner_scenario(run, "week/carry_skips_started_subtasks", week_today="2024-01-10")


def test_week_cancel_delete(run_planner_scenario):
    """Press backspace then cancel the delete dialog — task must remain unchanged."""
    async def run(pilot, app):
        await pilot.press("backspace")   # delete dialog opens
        await pilot.pause()
        if isinstance(app.screen, SaveDialog):
            await pilot.click("#no")     # cancel delete
            await pilot.pause()

    run_planner_scenario(run, "week/cancel_delete", week_today="2024-01-02")


def test_day_extend_end_time(run_planner_scenario):
    """Day view: extend end time on a start-only timed task creates a 15-min slot."""
    async def run(pilot, app):
        await pilot.press("L")           # extend 09:00 → 09:00-9:15
        await pilot.pause()
        await _save(pilot, app)

    run_planner_scenario(run, "day/extend_end_time", date="2024-01-02")


def test_day_shrink_end_time(run_planner_scenario):
    """Day view: extend twice then shrink once — net result is one 15-min extension."""
    async def run(pilot, app):
        await pilot.press("L")           # 09:00 → 09:00-9:15
        await pilot.pause()
        await pilot.press("L")           # → 09:00-9:30
        await pilot.pause()
        await pilot.press("H")           # → 09:00-9:15
        await pilot.pause()
        await _save(pilot, app)

    run_planner_scenario(run, "day/shrink_end_time", date="2024-01-02")


def test_day_remove_time(run_planner_scenario):
    """Day view: remove time from a timed task — task becomes untimed."""
    async def run(pilot, app):
        await pilot.press("r")           # remove time from Morning standup
        await pilot.pause()
        await _save(pilot, app)

    run_planner_scenario(run, "day/remove_time", date="2024-01-02")


def _task(title, indent=''):
    return Task(title=title, status='todo', time=None, line_number=-1, indent=indent)


def _expected(scenario, filename):
    path = os.path.join(_EXPECTED_DIR, scenario, filename)
    with open(path, encoding='utf-8') as f:
        return f.read()


def test_day_insert_top_level_no_preceding_blank():
    """New top-level task appended to file with no trailing blank — follows directly, gets trailing blank."""
    nodes = parse(os.path.join(_INPUT_DIR, '2024-01-03.md'))
    insert_task(nodes, _task('standup'))
    assert serialize(nodes) == _expected('insert_top_level_no_preceding_blank', '2024-01-03.md')


def test_day_insert_top_level_with_preceding_blank():
    """New top-level task appended to file whose last task already has a trailing blank — blank is preserved as separator."""
    nodes = parse(os.path.join(_INPUT_DIR, '2024-01-02.md'))
    insert_task(nodes, _task('standup'))
    assert serialize(nodes) == _expected('insert_top_level_with_preceding_blank', '2024-01-02.md')


def test_day_insert_subtask():
    """New subtask appended to parent — no blank lines added anywhere."""
    nodes = parse(os.path.join(_INPUT_DIR, '2024-01-03.md'))
    parent = next(n for n in nodes if isinstance(n, TaskBlock))
    insert_task(parent.nodes, _task('Retrospective', indent='    '))
    assert serialize(nodes) == _expected('insert_subtask', '2024-01-03.md')
