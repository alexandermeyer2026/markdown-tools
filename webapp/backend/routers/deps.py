import os
import re
from pathlib import Path
from fastapi import HTTPException

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def journal_dir() -> Path:
    d = Path(os.getenv("JOURNAL_DIR", "."))
    d.mkdir(parents=True, exist_ok=True)
    return d


def resolve_journal_file(date: str) -> Path:
    if not _DATE_RE.match(date):
        raise HTTPException(status_code=400, detail="Date must be YYYY-MM-DD")
    path = journal_dir() / f"{date}.md"
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return path
