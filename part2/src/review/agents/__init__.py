from pathlib import Path

from langchain.agents import create_agent


def read_prompt(name: str) -> str:
    path = Path(__file__).resolve().parents[1] / "prompts" / name
    return path.read_text()


def findings_schema() -> dict:
    return {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "filename": {"type": "string"},
                "finding": {"type": "string"},
            },
            "required": ["filename", "finding"],
        },
    }


def make(model, tools, prompt: str, schema: dict, name: str, middleware=()):
    return create_agent(
        model=model,
        tools=tools,
        system_prompt=read_prompt(prompt),
        response_format=schema,
        name=name,
        middleware=middleware,
    )
