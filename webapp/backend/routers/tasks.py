import os
import re
from pathlib import Path
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional

from .auth import get_current_user

from parser.task_parser import TaskParser
from models.task import Task
from os_utils.backup_manager import BackupManager

router = APIRouter()

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _journal_dir() -> Path:
    return Path(os.getenv("JOURNAL_DIR", "."))


def _resolve(date: str) -> Path:
    if not _DATE_RE.match(date):
        raise HTTPException(status_code=400, detail="Date must be YYYY-MM-DD")
    path = _journal_dir() / f"{date}.md"
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return path


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
    path = _resolve(date)
    try:
        all_tasks = TaskParser.parse_file(str(path))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not parse file: {e}")
    top_level = [t for t in all_tasks if t.parent is None]
    return {"date": date, "tasks": [_task_to_dict(t) for t in top_level]}


@router.post("/{date}")
def create_task(date: str, req: CreateTaskRequest, _user=Depends(get_current_user)):
    if req.status not in Task.STATUS_CHAR:
        raise HTTPException(status_code=400, detail=f"Invalid status")

    path = _resolve(date)
    BackupManager.backup(str(path), str(_journal_dir()))

    time_part = ""
    if req.time_start:
        time_part = req.time_start
        if req.time_end:
            time_part += f"-{req.time_end}"
        time_part += " "

    if "\n" in req.title or "\r" in req.title:
        raise HTTPException(status_code=400, detail="Title cannot contain newlines")

    char = Task.STATUS_CHAR[req.status]
    line = f"- [{char}] {time_part}{req.title}\n"

    with open(path, "a") as f:
        f.write(line)

    return {"message": "created"}


@router.patch("/{date}/{line_number}")
def update_task_status(
    date: str,
    line_number: int,
    req: UpdateTaskRequest,
    _user=Depends(get_current_user),
):
    if req.status not in Task.STATUS_CHAR:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Valid values: {list(Task.STATUS_CHAR.keys())}",
        )

    path = _resolve(date)
    all_tasks = TaskParser.parse_file(str(path))
    task = next((t for t in all_tasks if t.line_number == line_number), None)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found at that line")

    BackupManager.backup(str(path), str(_journal_dir()))

    task.status = req.status
    lines = path.read_text().splitlines(keepends=False)
    lines[line_number - 1] = task.to_line()
    path.write_text("\n".join(lines) + "\n")

    return {"message": "updated", "task": _task_to_dict(task)}
