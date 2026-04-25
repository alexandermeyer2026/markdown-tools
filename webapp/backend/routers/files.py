import os
import re
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from fastapi.responses import FileResponse

from .auth import get_current_user

router = APIRouter()

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _journal_dir() -> Path:
    d = Path(os.getenv("JOURNAL_DIR", "."))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _resolve(date: str) -> Path:
    if not _DATE_RE.match(date):
        raise HTTPException(status_code=400, detail="Date must be YYYY-MM-DD")
    path = _journal_dir() / f"{date}.md"
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return path


@router.get("")
def list_files(_user=Depends(get_current_user)):
    d = _journal_dir()
    dates = sorted(
        [f.stem for f in d.glob("*.md") if _DATE_RE.match(f.stem)],
        reverse=True,
    )
    return {"dates": dates}


@router.post("/upload")
async def upload_file(file: UploadFile = File(...), _user=Depends(get_current_user)):
    raw_name = file.filename or ""
    safe_name = Path(raw_name).name  # strip any directory components
    if not safe_name.endswith(".md"):
        raise HTTPException(status_code=400, detail="Only .md files are accepted")
    stem = Path(safe_name).stem
    if not _DATE_RE.match(stem):
        raise HTTPException(status_code=400, detail="Filename must be YYYY-MM-DD.md")

    content = await file.read()
    dest = (_journal_dir() / safe_name).resolve()
    if not dest.is_relative_to(_journal_dir().resolve()):
        raise HTTPException(status_code=400, detail="Invalid filename")
    dest.write_bytes(content)
    return {"date": stem, "message": "uploaded"}


@router.get("/{date}/download")
def download_file(date: str, _user=Depends(get_current_user)):
    path = _resolve(date)
    return FileResponse(path, filename=f"{date}.md", media_type="text/markdown")


@router.delete("/{date}")
def delete_file(date: str, _user=Depends(get_current_user)):
    path = _resolve(date)
    path.unlink()
    return {"message": "deleted"}
