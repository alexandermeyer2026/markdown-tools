from pathlib import Path
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from fastapi.responses import FileResponse, Response

from .auth import get_current_user
from .deps import _DATE_RE, journal_dir, resolve_journal_file
from tools.journal_tools.ics_tool import _build_ics, _collect_vevent_lines
from os_utils import FileFinder
from models.file import parse

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


@router.get("/export/ics")
def export_ics(_user=Depends(get_current_user)):
    files = FileFinder.find_journal_files(str(journal_dir()))
    all_events = []
    counter = [0]
    for file_path in files:
        date = FileFinder.get_journal_file_date(file_path)
        nodes = parse(file_path)
        all_events.extend(_collect_vevent_lines(nodes, date, counter))
    content = _build_ics(all_events)
    return Response(
        content=content.encode('utf-8'),
        media_type='text/calendar',
        headers={'Content-Disposition': 'attachment; filename="journal.ics"'},
    )


@router.get("/{date}/download")
def download_file(date: str, _user=Depends(get_current_user)):
    path = resolve_journal_file(date)
    return FileResponse(path, filename=f"{date}.md", media_type="text/markdown")


@router.delete("/{date}")
def delete_file(date: str, _user=Depends(get_current_user)):
    path = resolve_journal_file(date)
    path.unlink()
    return {"message": "deleted"}
