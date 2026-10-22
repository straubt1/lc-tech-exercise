from review.agents import findings_schema, make

SCHEMA = {
    "title": "SecurityResult",
    "description": "Security findings at or above the minimum named in the user message.",
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["pass", "fail"]},
        "findings": findings_schema(),
    },
    "required": ["status", "findings"],
}


def build(model, tools):
    return make(model, tools, "security.md", SCHEMA, "security")
