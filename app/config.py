import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel

_BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(_BASE_DIR / ".env")


class Settings(BaseModel):
    llm_provider: str = os.environ.get("LLM_PROVIDER", "anthropic")
    anthropic_api_key: str = os.environ.get("ANTHROPIC_API_KEY", "")
    claude_model: str = os.environ.get("CLAUDE_MODEL", "claude-opus-4-5")
    openai_api_key: str = os.environ.get("OPENAI_API_KEY", "")
    # Default to a stable, general model; users can override in .env
    openai_model: str = os.environ.get("OPENAI_MODEL", "gpt-4o")
    openai_base_url: str = os.environ.get("OPENAI_BASE_URL", "")

    base_dir: Path = _BASE_DIR
    storage_dir: Path = base_dir / "storage"
    resumes_dir: Path = storage_dir / "resumes"
    index_dir: Path = storage_dir / "index"
    generated_resumes_dir: Path = storage_dir / "generated_resumes"
    resume_output_dir: Path = Path(os.environ.get("RESUME_OUTPUT_DIR", r"C:\Users\krant\OneDrive\Desktop\resumes_tailored"))

    embed_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    docx_template_path: str = str(base_dir / "storage" / "resumes" / "template" / "template.docx")


settings = Settings()

settings.resumes_dir.mkdir(parents=True, exist_ok=True)
settings.index_dir.mkdir(parents=True, exist_ok=True)
settings.generated_resumes_dir.mkdir(parents=True, exist_ok=True)
settings.resume_output_dir.mkdir(parents=True, exist_ok=True)
