from pathlib import Path
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from fastapi.responses import FileResponse

from .auth import get_current_user
from .deps import _DATE_RE, journal_dir, resolve_journal_file

router = APIRouter()


@router.get("")
def list_files(_user=Depends(get_current_user)):
    d = journal_dir()
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
    dest = (journal_dir() / safe_name).resolve()
    if not dest.is_relative_to(journal_dir().resolve()):
        raise HTTPException(status_code=400, detail="Invalid filename")
    dest.write_bytes(content)
    return {"date": stem, "message": "uploaded"}


@router.get("/{date}/download")
def download_file(date: str, _user=Depends(get_current_user)):
    path = resolve_journal_file(date)
    return FileResponse(path, filename=f"{date}.md", media_type="text/markdown")


@router.delete("/{date}")
def delete_file(date: str, _user=Depends(get_current_user)):
    path = resolve_journal_file(date)
    path.unlink()
    return {"message": "deleted"}
