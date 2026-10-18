"""Environment for the releaser. GH_TOKEN is never copied onto settings or graph state."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

DEFAULT_REPO = "straubt1/terraform-aws-object-storage"
DEFAULT_CANDIDATE_REF = "latest"
LANGSMITH_CLOUD_ENDPOINT = "https://api.smith.langchain.com"


@dataclass(frozen=True)
class Settings:
    github_repo: str
    candidate_ref: str
    model: str
    langsmith_tracing: bool
    langsmith_api_key: str
    langsmith_project: str
    langsmith_endpoint: str
    release_enabled: bool


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes"}


def split_repo(repo: str) -> tuple[str, str]:
    owner, _, name = repo.partition("/")
    if not owner or not name or "/" in name:
        raise RuntimeError(f"GITHUB_REPO must be owner/name, got {repo!r}")
    return owner, name


def load_settings() -> Settings:
    load_dotenv()
    repo = os.environ.get("GITHUB_REPO", DEFAULT_REPO).strip() or DEFAULT_REPO
    split_repo(repo)
    candidate = os.environ.get("GITHUB_CANDIDATE_REF", DEFAULT_CANDIDATE_REF).strip()
    endpoint = os.environ.get("LANGSMITH_ENDPOINT", LANGSMITH_CLOUD_ENDPOINT).strip()
    return Settings(
        github_repo=repo,
        candidate_ref=candidate or DEFAULT_CANDIDATE_REF,
        model=os.environ.get("MODEL", "").strip(),
        langsmith_tracing=_flag("LANGSMITH_TRACING"),
        langsmith_api_key=os.environ.get("LANGSMITH_API_KEY", "").strip(),
        langsmith_project=os.environ.get("LANGSMITH_PROJECT", "").strip(),
        langsmith_endpoint=endpoint or LANGSMITH_CLOUD_ENDPOINT,
        release_enabled=_flag("RELEASE_ENABLED"),
    )
