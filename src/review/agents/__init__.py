from pathlib import Path


def read_prompt(name: str) -> str:
    path = Path(__file__).resolve().parents[1] / "prompts" / name
    return path.read_text()
