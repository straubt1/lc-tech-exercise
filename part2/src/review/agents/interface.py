from review.agents import findings_schema, make

SCHEMA = {
    "title": "InterfaceResult",
    "description": "Whether the module interface matches the readme.",
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["pass", "fail"]},
        "findings": findings_schema(),
    },
    "required": ["status", "findings"],
}


def build(model, tools, middleware=()):
    return make(model, tools, "interface.md", SCHEMA, "interface", middleware)
