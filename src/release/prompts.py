"""Load agent prompts from files. Prompts are not stored as inline strings."""

from pathlib import Path

PROMPTS_DIR = Path(__file__).parent / "prompts"


def load_prompt(name: str) -> str:
    path = PROMPTS_DIR / name
    if path.suffix != ".md" or not path.is_file():
        raise FileNotFoundError(f"prompt file not found: {name}")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise RuntimeError(f"prompt file is empty: {name}")
    return text
