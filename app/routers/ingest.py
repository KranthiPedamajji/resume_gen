from fastapi import APIRouter, UploadFile, File, HTTPException
from pathlib import Path
import shutil

from app.models.schemas import IngestResponse, TemplateListResponse, ResumeListResponse, DeleteResumeResponse
from app.services.indexing import build_and_save_index
from app.config import settings

router = APIRouter()


@router.get("/resumes/templates", response_model=TemplateListResponse)
def list_template_resumes() -> TemplateListResponse:
    """List resume template files available under storage/resumes/template."""
    template_dir = settings.resumes_dir / "template"
    if not template_dir.exists() or not template_dir.is_dir():
        return TemplateListResponse(files=[])

    allowed = {".pdf", ".doc", ".docx", ".txt"}
    files = [p.name for p in template_dir.iterdir() if p.is_file() and p.suffix.lower() in allowed]
    files.sort()
    return TemplateListResponse(files=files)


@router.get("/resumes", response_model=ResumeListResponse)
def list_uploaded_resumes() -> ResumeListResponse:
    """List user-uploaded resumes under storage/resumes (excluding template folder)."""
    root = settings.resumes_dir
    if not root.exists() or not root.is_dir():
        return ResumeListResponse(files=[])

    allowed = {".pdf", ".doc", ".docx", ".txt"}
    files: list[str] = []

    for p in root.rglob("*"):
        if p.is_dir():
            # skip template folder
            if p.name.lower() == "template":
                continue
            # skip hidden dirs
            if p.name.startswith('.'):
                continue
            continue
        if p.suffix.lower() not in allowed:
            continue
        # skip files inside template folder
        if any(part.lower() == "template" for part in p.relative_to(root).parts):
            continue
        rel_path = str(p.relative_to(root).as_posix())
        files.append(rel_path)

    files.sort()
    return ResumeListResponse(files=files)


# Allow preflight for CORS
@router.options("/resumes/templates")
async def options_templates():
    return {}


@router.options("/resumes")
async def options_resumes():
    return {}


@router.post("/upload-resumes", response_model=IngestResponse)
async def upload_resumes(files: list[UploadFile] = File(...)) -> IngestResponse:
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded.")

    saved = []
    for f in files:
        suffix = Path(f.filename).suffix.lower()
        if suffix not in {".pdf", ".docx", ".txt"}:
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {f.filename}")

        dest = settings.resumes_dir / Path(f.filename).name
        with dest.open("wb") as out:
            shutil.copyfileobj(f.file, out)
        saved.append(dest.name)

    try:
        indexed_chunks, saved_files = build_and_save_index(
            resumes_dir=settings.resumes_dir,
            index_dir=settings.index_dir,
            embed_model_name=settings.embed_model,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return IngestResponse(indexed_chunks=indexed_chunks, saved_files=saved_files)


@router.post("/reindex", response_model=IngestResponse)
def reindex() -> IngestResponse:
    try:
        indexed_chunks, saved_files = build_and_save_index(
            resumes_dir=settings.resumes_dir,
            index_dir=settings.index_dir,
            embed_model_name=settings.embed_model,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return IngestResponse(indexed_chunks=indexed_chunks, saved_files=saved_files)


@router.delete("/resumes/{resume_path:path}", response_model=DeleteResumeResponse)
def delete_resume(resume_path: str) -> DeleteResumeResponse:
    root = settings.resumes_dir
    target = (root / resume_path).resolve()

    try:
        root_resolved = root.resolve()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Resumes directory not found")

    if root_resolved not in target.parents and target != root_resolved:
        raise HTTPException(status_code=400, detail="Invalid path")

    if any(part.lower() == "template" for part in target.relative_to(root_resolved).parts):
        raise HTTPException(status_code=400, detail="Cannot delete template files")

    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    if target.suffix.lower() not in {".pdf", ".doc", ".docx", ".txt"}:
        raise HTTPException(status_code=400, detail="Unsupported file type")

    try:
        target.unlink()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    try:
        indexed_chunks, saved_files = build_and_save_index(
            resumes_dir=settings.resumes_dir,
            index_dir=settings.index_dir,
            embed_model_name=settings.embed_model,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return DeleteResumeResponse(
        deleted=str(target.relative_to(root_resolved).as_posix()),
        indexed_chunks=indexed_chunks,
        remaining_files=saved_files,
    )
