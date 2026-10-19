from langchain.agents import create_agent

from review.agents import read_prompt

SCHEMA = {
    "title": "ReviewResult",
    "description": "Review status and findings.",
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["pass", "fail"]},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string"},
                    "finding": {"type": "string"},
                },
                "required": ["filename", "finding"],
            },
        },
    },
    "required": ["status", "findings"],
}


def build(model, tools):
    return create_agent(
        model=model,
        tools=tools,
        system_prompt=read_prompt("review.md"),
        response_format=SCHEMA,
        name="review",
    )
