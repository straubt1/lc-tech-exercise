"""LangSmith cloud tracing. The API key stays in the environment."""

import os

from release.config import Settings


def configure_langsmith(settings: Settings) -> None:
    os.environ["LANGSMITH_ENDPOINT"] = settings.langsmith_endpoint
    if not settings.langsmith_tracing:
        os.environ["LANGSMITH_TRACING"] = "false"
        return
    if not settings.langsmith_api_key or not settings.langsmith_project:
        raise RuntimeError("LANGSMITH_TRACING requires LANGSMITH_API_KEY and LANGSMITH_PROJECT")
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
