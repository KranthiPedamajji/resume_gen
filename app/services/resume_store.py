from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple, Dict, Any
import json
import shutil
from datetime import datetime, timezone

from app.models.schemas import ResumeState


def init_resume_record(
    root_dir: Path,
    resume_id: str,
    state: ResumeState,
    resume_text: str,
    jd_text: Optional[str] = None,
    resume_docx_path: Optional[Path] = None,
    source: str = "generate",
) -> Dict[str, Any]:
    """Create a new resume record with version v1."""
    resume_dir = root_dir / resume_id
    resume_dir.mkdir(parents=True, exist_ok=True)
    version = "v1"
    version_dir = resume_dir / version
    version_dir.mkdir(parents=True, exist_ok=True)

    resume_json = version_dir / "resume.json"
    resume_txt = version_dir / "resume.txt"
    resume_json.write_text(state.model_dump_json(indent=2), encoding="utf-8")
    resume_txt.write_text(resume_text, encoding="utf-8")

    jd_path = None
    if jd_text:
        jd_path = version_dir / "job_description.txt"
        jd_path.write_text(jd_text, encoding="utf-8")

    docx_path = None
    if resume_docx_path and resume_docx_path.exists():
        docx_path = version_dir / "resume.docx"
        shutil.copy2(resume_docx_path, docx_path)

    meta = {
        "resume_id": resume_id,
        "created_at": _now_iso(),
        "latest_version": version,
        "source": source,
        "versions": [
            {
                "version": version,
                "created_at": _now_iso(),
                "resume_json": str(resume_json),
                "resume_txt": str(resume_txt),
                "resume_docx": str(docx_path) if docx_path else None,
                "job_description": str(jd_path) if jd_path else None,
            }
        ],
    }
    _write_meta(resume_dir, meta)
    return meta


def append_resume_version(
    root_dir: Path,
    resume_id: str,
    state: ResumeState,
    resume_text: Optional[str] = None,
    jd_text: Optional[str] = None,
    resume_docx_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Append a new version to an existing resume record."""
    resume_dir = root_dir / resume_id
    meta = load_meta(resume_dir)
    version = _next_version(meta)
    version_dir = resume_dir / version
    version_dir.mkdir(parents=True, exist_ok=True)

    resume_json = version_dir / "resume.json"
    resume_json.write_text(state.model_dump_json(indent=2), encoding="utf-8")

    resume_txt = None
    if resume_text:
        resume_txt = version_dir / "resume.txt"
        resume_txt.write_text(resume_text, encoding="utf-8")

    jd_path = None
    if jd_text:
        jd_path = version_dir / "job_description.txt"
        jd_path.write_text(jd_text, encoding="utf-8")
    else:
        latest_jd = _latest_file(meta, "job_description")
        if latest_jd:
            jd_path = version_dir / "job_description.txt"
            shutil.copy2(latest_jd, jd_path)

    docx_path = None
    if resume_docx_path and resume_docx_path.exists():
        docx_path = version_dir / "resume.docx"
        shutil.copy2(resume_docx_path, docx_path)

    meta["latest_version"] = version
    meta["versions"].append(
        {
            "version": version,
            "created_at": _now_iso(),
            "resume_json": str(resume_json),
            "resume_txt": str(resume_txt) if resume_txt else None,
            "resume_docx": str(docx_path) if docx_path else None,
            "job_description": str(jd_path) if jd_path else None,
        }
    )
    _write_meta(resume_dir, meta)
    return meta


def load_resume_state(root_dir: Path, resume_id: str, version: Optional[str] = None) -> Tuple[ResumeState, str]:
    """Load the resume state for the latest or requested version."""
    resume_dir = root_dir / resume_id
    meta = load_meta(resume_dir)
    version_name = version or meta.get("latest_version")
    if not version_name:
        raise FileNotFoundError("No versions found for resume_id.")
    resume_json = resume_dir / version_name / "resume.json"
    data = json.loads(resume_json.read_text(encoding="utf-8"))
    return ResumeState(**data), version_name


def load_latest_resume_text(root_dir: Path, resume_id: str) -> Optional[str]:
    """Load latest resume.txt for a resume_id if available."""
    resume_dir = root_dir / resume_id
    meta = load_meta(resume_dir)
    latest_txt = _latest_file(meta, "resume_txt")
    if latest_txt and latest_txt.exists():
        return latest_txt.read_text(encoding="utf-8")
    return None


def load_latest_state(root_dir: Path, resume_id: str) -> Tuple[ResumeState, str]:
    """Load the latest resume state."""
    return load_resume_state(root_dir, resume_id, version=None)


def load_latest_jd_text(root_dir: Path, resume_id: str) -> Optional[str]:
    """Load the latest available job_description.txt for a resume_id."""
    resume_dir = root_dir / resume_id
    meta = load_meta(resume_dir)
    jd_path = _latest_file(meta, "job_description")
    if jd_path and jd_path.exists():
        return jd_path.read_text(encoding="utf-8")
    return None


def load_meta(resume_dir: Path) -> Dict[str, Any]:
    meta_path = resume_dir / "meta.json"
    if not meta_path.exists():
        raise FileNotFoundError("meta.json not found for resume_id.")
    return json.loads(meta_path.read_text(encoding="utf-8"))


def latest_version_dir(root_dir: Path, resume_id: str) -> Path:
    resume_dir = root_dir / resume_id
    meta = load_meta(resume_dir)
    version = meta.get("latest_version")
    if not version:
        raise FileNotFoundError("No versions found for resume_id.")
    return resume_dir / version


def create_next_version(root_dir: Path, resume_id: str) -> Tuple[str, Path]:
    """Create the next version directory and return (version, path)."""
    resume_dir = root_dir / resume_id
    meta = load_meta(resume_dir)
    version = _next_version(meta)
    version_dir = resume_dir / version
    version_dir.mkdir(parents=True, exist_ok=True)
    return version, version_dir


def update_meta_latest(root_dir: Path, resume_id: str, version: str) -> None:
    """Update meta.json latest_version without changing entries."""
    resume_dir = root_dir / resume_id
    meta = load_meta(resume_dir)
    meta["latest_version"] = version
    _write_meta(resume_dir, meta)


def update_version_docx_path(root_dir: Path, resume_id: str, version: str, docx_path: Path) -> None:
    """Update meta.json with the DOCX path for a given version."""
    resume_dir = root_dir / resume_id
    meta = load_meta(resume_dir)
    for entry in meta.get("versions", []):
        if entry.get("version") == version:
            entry["resume_docx"] = str(docx_path)
            break
    _write_meta(resume_dir, meta)


def _write_meta(resume_dir: Path, meta: Dict[str, Any]) -> None:
    meta_path = resume_dir / "meta.json"
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")


def _next_version(meta: Dict[str, Any]) -> str:
    versions = meta.get("versions", [])
    return f"v{len(versions) + 1}"


def _latest_file(meta: Dict[str, Any], key: str) -> Optional[Path]:
    versions = meta.get("versions", [])
    for entry in reversed(versions):
        path = entry.get(key)
        if path:
            return Path(path)
    return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
