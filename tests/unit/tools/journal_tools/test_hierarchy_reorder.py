"""Unit tests for tab_task, shift_tab_task, and move_block_in_nodes."""
import unittest

from config import get_indent_step
from models import Task, TaskTime
from models.file import RawLine, TaskBlock
from models.file import (
    move_block_in_nodes,
    shift_tab_task,
    tab_task,
)

STEP = get_indent_step()  # '    ' (4 spaces) from task_config.yaml


def _task(title: str, indent: str = '', timed: bool = False) -> Task:
    time = TaskTime(start='9:00') if timed else None
    return Task(title=title, status='todo', time=time, line_number=-1, indent=indent)


def _block(task: Task, children: list | None = None) -> TaskBlock:
    return TaskBlock(task=task, header=task.to_line() + '\n', nodes=list(children or []))


class TestTabTask(unittest.TestCase):

    def test_no_preceding_sibling_returns_false(self):
        t = _task('A')
        nodes = [_block(t)]
        self.assertFalse(tab_task(nodes, t))

    def test_preceding_rawline_only_returns_false(self):
        t = _task('A')
        nodes = [RawLine('\n'), _block(t)]
        self.assertFalse(tab_task(nodes, t))

    def test_task_not_found_returns_false(self):
        nodes = [_block(_task('X'))]
        self.assertFalse(tab_task(nodes, _task('Missing')))

    def test_moves_block_into_preceding_sibling(self):
        a, b = _task('A'), _task('B')
        a_block, b_block = _block(a), _block(b)
        nodes = [a_block, b_block]
        self.assertTrue(tab_task(nodes, b))
        self.assertEqual(nodes, [a_block])
        self.assertIn(b_block, a_block.nodes)

    def test_updates_task_indent(self):
        a, b = _task('A'), _task('B')
        nodes = [_block(a), _block(b)]
        tab_task(nodes, b)
        self.assertEqual(b.indent, a.indent + STEP)

    def test_updates_header_after_tab(self):
        a, b = _task('A'), _task('B')
        a_block = _block(a)
        b_block = _block(b)
        nodes = [a_block, b_block]
        tab_task(nodes, b)
        self.assertIn(STEP, b_block.header)

    def test_recursively_updates_child_indent(self):
        a = _task('A')
        b = _task('B')
        c = _task('C', indent=STEP)
        b_block = _block(b, children=[_block(c)])
        nodes = [_block(a), b_block]
        tab_task(nodes, b)
        self.assertEqual(b.indent, STEP)
        self.assertEqual(c.indent, STEP * 2)

    def test_updates_body_rawline_indent(self):
        a, b = _task('A'), _task('B')
        b_block = _block(b)
        b_block.nodes.append(RawLine(STEP + 'Body line\n'))
        nodes = [_block(a), b_block]
        tab_task(nodes, b)
        raw = b_block.nodes[0].raw
        self.assertTrue(raw.startswith(STEP * 2), repr(raw))
        self.assertIn('Body line', raw)

    def test_preceding_sibling_with_rawline_separator(self):
        a, b = _task('A'), _task('B')
        a_block, b_block = _block(a), _block(b)
        nodes = [a_block, RawLine('\n'), b_block]
        self.assertTrue(tab_task(nodes, b))
        self.assertIn(b_block, a_block.nodes)

    def test_tab_twice_gives_nested_children(self):
        # After tab-ing B under A, C's preceding sibling in top-level is A → C also under A
        a, b, c = _task('A'), _task('B'), _task('C')
        a_block, b_block, c_block = _block(a), _block(b), _block(c)
        nodes = [a_block, b_block, c_block]
        tab_task(nodes, b)   # nodes=[a_block, c_block]; a_block.nodes=[b_block]
        tab_task(nodes, c)   # nodes=[a_block];          a_block.nodes=[b_block, c_block]
        self.assertEqual(nodes, [a_block])
        child_blocks = [n for n in a_block.nodes if isinstance(n, TaskBlock)]
        self.assertIn(b_block, child_blocks)
        self.assertIn(c_block, child_blocks)


class TestShiftTabTask(unittest.TestCase):

    def test_top_level_task_returns_false(self):
        t = _task('A')
        nodes = [_block(t)]
        self.assertFalse(shift_tab_task(nodes, t))

    def test_task_not_found_returns_false(self):
        nodes = [_block(_task('A'))]
        self.assertFalse(shift_tab_task(nodes, _task('Missing')))

    def test_promotes_subtask_after_parent(self):
        parent = _task('Parent')
        child = _task('Child', indent=STEP)
        child_block = _block(child)
        parent_block = _block(parent, children=[child_block])
        nodes = [parent_block]
        self.assertTrue(shift_tab_task(nodes, child))
        self.assertEqual(nodes, [parent_block, child_block])
        self.assertNotIn(child_block, parent_block.nodes)

    def test_updates_indent_to_match_parent_level(self):
        parent = _task('Parent')
        child = _task('Child', indent=STEP)
        parent_block = _block(parent, children=[_block(child)])
        nodes = [parent_block]
        shift_tab_task(nodes, child)
        self.assertEqual(child.indent, parent.indent)

    def test_recursively_updates_grandchild_indent(self):
        parent = _task('Parent')
        child = _task('Child', indent=STEP)
        grandchild = _task('GC', indent=STEP * 2)
        child_block = _block(child, children=[_block(grandchild)])
        parent_block = _block(parent, children=[child_block])
        nodes = [parent_block]
        shift_tab_task(nodes, child)
        self.assertEqual(child.indent, '')
        self.assertEqual(grandchild.indent, STEP)

    def test_later_siblings_stay_in_parent(self):
        parent = _task('Parent')
        c1, c2 = _task('C1', indent=STEP), _task('C2', indent=STEP)
        c1_block, c2_block = _block(c1), _block(c2)
        parent_block = _block(parent, children=[c1_block, c2_block])
        nodes = [parent_block]
        shift_tab_task(nodes, c1)
        self.assertIn(c2_block, parent_block.nodes)
        self.assertEqual(nodes, [parent_block, c1_block])

    def test_tab_then_shift_tab_round_trips_position(self):
        a, b = _task('A'), _task('B')
        a_block, b_block = _block(a), _block(b)
        nodes = [a_block, b_block]
        tab_task(nodes, b)
        shift_tab_task(nodes, b)
        self.assertEqual(nodes, [a_block, b_block])
        self.assertEqual(b.indent, '')

    def test_tab_then_shift_tab_round_trips_body(self):
        a, b = _task('A'), _task('B')
        b_block = _block(b)
        b_block.nodes.append(RawLine(STEP + 'Note\n'))
        nodes = [_block(a), b_block]
        tab_task(nodes, b)
        shift_tab_task(nodes, b)
        raw = b_block.nodes[0].raw
        self.assertTrue(raw.startswith(STEP + 'Note'), repr(raw))


class TestMoveBlockInNodes(unittest.TestCase):

    def test_timed_task_not_moved(self):
        t = _task('A', timed=True)
        nodes = [_block(t), _block(_task('B'))]
        self.assertFalse(move_block_in_nodes(nodes, t, 1))

    def test_task_not_found_returns_false(self):
        nodes = [_block(_task('A'))]
        self.assertFalse(move_block_in_nodes(nodes, _task('X'), 1))

    def test_move_down(self):
        a, b = _task('A'), _task('B')
        a_block, b_block = _block(a), _block(b)
        nodes = [a_block, b_block]
        self.assertTrue(move_block_in_nodes(nodes, a, 1))
        self.assertEqual(nodes, [b_block, a_block])

    def test_move_up(self):
        a, b = _task('A'), _task('B')
        a_block, b_block = _block(a), _block(b)
        nodes = [a_block, b_block]
        self.assertTrue(move_block_in_nodes(nodes, b, -1))
        self.assertEqual(nodes, [b_block, a_block])

    def test_move_down_at_last_returns_false(self):
        a, b = _task('A'), _task('B')
        nodes = [_block(a), _block(b)]
        self.assertFalse(move_block_in_nodes(nodes, b, 1))

    def test_move_up_at_first_returns_false(self):
        a, b = _task('A'), _task('B')
        nodes = [_block(a), _block(b)]
        self.assertFalse(move_block_in_nodes(nodes, a, -1))

    def test_move_down_skips_timed_sibling(self):
        a = _task('A')
        t = _task('T', timed=True)
        b = _task('B')
        a_block, t_block, b_block = _block(a), _block(t), _block(b)
        nodes = [a_block, t_block, b_block]
        self.assertTrue(move_block_in_nodes(nodes, a, 1))
        self.assertEqual(nodes, [b_block, t_block, a_block])

    def test_move_preserves_rawline_separators(self):
        a, b = _task('A'), _task('B')
        a_block, b_block = _block(a), _block(b)
        sep = RawLine('\n')
        nodes = [a_block, sep, b_block]
        move_block_in_nodes(nodes, a, 1)
        self.assertEqual(nodes[1], sep)

    def test_works_on_subtask_within_parent(self):
        parent = _task('Parent')
        c1, c2 = _task('C1', indent=STEP), _task('C2', indent=STEP)
        c1_block, c2_block = _block(c1), _block(c2)
        parent_block = _block(parent, children=[c1_block, c2_block])
        nodes = [parent_block]
        self.assertTrue(move_block_in_nodes(nodes, c1, 1))
        self.assertEqual(parent_block.nodes, [c2_block, c1_block])

    def test_only_untimed_counted_as_swap_target(self):
        # All siblings are timed → can't move
        t1 = _task('T1', timed=True)
        t2 = _task('T2', timed=True)
        u = _task('U')
        nodes = [_block(t1), _block(u), _block(t2)]
        self.assertFalse(move_block_in_nodes(nodes, u, 1))
        self.assertFalse(move_block_in_nodes(nodes, u, -1))


if __name__ == '__main__':
    unittest.main()
