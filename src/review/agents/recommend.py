from langchain.agents import create_agent

from review.agents import read_prompt

SCHEMA = {
    "title": "RecommendResult",
    "description": "Suggestions and proposed README or CHANGELOG files.",
    "type": "object",
    "properties": {
        "suggestions": {"type": "string"},
        "pr_title": {"type": "string"},
        "pr_body": {"type": "string"},
        "proposed_files": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["filename", "content"],
            },
        },
    },
    "required": ["suggestions", "pr_title", "pr_body", "proposed_files"],
}


def build(model, tools):
    return create_agent(
        model=model,
        tools=tools,
        system_prompt=read_prompt("recommend.md"),
        response_format=SCHEMA,
        name="recommend",
    )
