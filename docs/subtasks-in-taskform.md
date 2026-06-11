# Subtasks in TaskForm — Requirements

## Overview

The `TaskFormScreen` gains a subtask section. Every task has subtasks; there is only one version of `TaskForm` — no distinction between "leaf" and "parent" tasks.

## Subtask Section Behaviour

| Aspect | Decision |
|--------|----------|
| Scope | Always present in every `TaskForm` |
| Content | All descendants of the task, indented by depth |
| Style | WeekScreen cells: `icon + title`, `bright_black`, `>` cursor on selected row |
| Empty state | Visible area with `"press n to add"` hint |
| Focus | One Tab stop; Tab from list → Save/Cancel buttons |
| Navigation | `j` / `k` within the list |
| `n` | Opens nested `TaskForm` overlay; on save → appends as direct child of the task being edited; on escape → discards |
| `Enter` | Opens selected subtask's `TaskForm`; on save → updates subtask in place, list refreshes |
| `D` | Confirmation prompt → delete selected subtask + entire subtree |
| Recursion | One `TaskForm` for all cases; sub-subtasks managed the same way |

## Data

- Title + status are shown per row in the subtask list (no time/notes visible at this level).
- Deleting a subtask deletes its whole subtree (confirmed by prompt).
- New subtasks added via `n` are always appended as direct children of the task currently open in the form (not as children of the selected subtask).
