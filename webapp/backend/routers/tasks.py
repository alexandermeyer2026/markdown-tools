import textwrap
from pathlib import Path
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional

from .auth import get_current_user
from .deps import journal_dir, resolve_journal_file

from models.file import RawLine, TaskBlock, parse, all_tasks
from models.task import Task, status_char_map
from os_utils.backup_manager import BackupManager
from os_utils.file_writer import FileWriter

router = APIRouter()


def _find_block(nodes: list, task: Task) -> 'TaskBlock | None':
    for node in nodes:
        if isinstance(node, TaskBlock):
            if node.task is task:
                return node
            result = _find_block(node.nodes, task)
            if result is not None:
                return result
    return None


def _task_to_dict(block: TaskBlock) -> dict:
    task = block.task
    body_lines = [n.raw.rstrip('\n') for n in block.nodes if isinstance(n, RawLine)]
    body_text = textwrap.dedent('\n'.join(body_lines)).strip() if body_lines else None
    return {
        "title": task.title,
        "status": task.status,
        "time": {"start": task.time.start, "end": task.time.end} if task.time else None,
        "line_number": task.line_number,
        "indent": task.indent,
        "body": body_text or None,
        "children": [_task_to_dict(n) for n in block.nodes if isinstance(n, TaskBlock)],
    }


class CreateTaskRequest(BaseModel):
    title: str
    status: str = "todo"
    time_start: Optional[str] = None
    time_end: Optional[str] = None


class UpdateTaskRequest(BaseModel):
    status: str


@router.get("/{date}")
def get_tasks(date: str, _user=Depends(get_current_user)):
    path = resolve_journal_file(date)
    try:
        nodes = parse(str(path))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not parse file: {e}")
    top_level_blocks = [n for n in nodes if isinstance(n, TaskBlock)]
    return {"date": date, "tasks": [_task_to_dict(b) for b in top_level_blocks]}


@router.post("/{date}")
def create_task(date: str, req: CreateTaskRequest, _user=Depends(get_current_user)):
    char_map = status_char_map()
    if req.status not in char_map:
        raise HTTPException(status_code=400, detail=f"Invalid status")

    path = resolve_journal_file(date)
    BackupManager.backup(str(path), str(journal_dir()))

    time_part = ""
    if req.time_start:
        time_part = req.time_start
        if req.time_end:
            time_part += f"-{req.time_end}"
        time_part += " "

    if "\n" in req.title or "\r" in req.title:
        raise HTTPException(status_code=400, detail="Title cannot contain newlines")

    char = char_map[req.status]
    line = f"- [{char}] {time_part}{req.title}\n"

    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    FileWriter.write_atomic(str(path), lines + [line])

    return {"message": "created"}


@router.patch("/{date}/{line_number}")
def update_task_status(
    date: str,
    line_number: int,
    req: UpdateTaskRequest,
    _user=Depends(get_current_user),
):
    char_map = status_char_map()
    if req.status not in char_map:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Valid values: {list(char_map.keys())}",
        )

    path = resolve_journal_file(date)
    nodes = parse(str(path))
    task = next((t for t in all_tasks(nodes) if t.line_number == line_number), None)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found at that line")

    BackupManager.backup(str(path), str(journal_dir()))

    task.status = req.status
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    lines[line_number - 1] = task.to_line() + "\n"
    FileWriter.write_atomic(str(path), lines)

    found_block = _find_block(nodes, task)
    return {"message": "updated", "task": _task_to_dict(found_block) if found_block else {"title": task.title, "status": task.status}}
