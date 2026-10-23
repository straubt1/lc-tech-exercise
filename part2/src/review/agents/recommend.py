from review.agents import make

SCHEMA = {
    "title": "RecommendResult",
    "description": "Suggestions, the pull request text, and the full new text of every file in the apply list.",
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
    return make(model, tools, "recommend.md", SCHEMA, "recommend")
