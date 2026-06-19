from pathlib import Path
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional

from .auth import get_current_user
from .deps import journal_dir, resolve_journal_file

from parser.file_model import parse, populate_task_relations, TaskBlock, all_tasks
from models.task import Task, status_char_map
from os_utils.backup_manager import BackupManager
from os_utils.file_writer import FileWriter

router = APIRouter()


def _task_to_dict(task: Task) -> dict:
    return {
        "title": task.title,
        "status": task.status,
        "time": {"start": task.time.start, "end": task.time.end} if task.time else None,
        "line_number": task.line_number,
        "indent": task.indent,
        "body": task.body,
        "children": [_task_to_dict(c) for c in task.children],
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
        populate_task_relations(nodes)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not parse file: {e}")
    top_level = [n.task for n in nodes if isinstance(n, TaskBlock)]
    return {"date": date, "tasks": [_task_to_dict(t) for t in top_level]}


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
    populate_task_relations(nodes)
    task = next((t for t in all_tasks(nodes) if t.line_number == line_number), None)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found at that line")

    BackupManager.backup(str(path), str(journal_dir()))

    task.status = req.status
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    lines[line_number - 1] = task.to_line() + "\n"
    FileWriter.write_atomic(str(path), lines)

    return {"message": "updated", "task": _task_to_dict(task)}
