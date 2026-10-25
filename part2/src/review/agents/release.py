from review.agents import findings_schema, make

SCHEMA = {
    "title": "ReleaseResult",
    "description": "Whether the module is ready to release, and the recommended version.",
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["ready", "not ready"]},
        "suggested_version": {"type": "string"},
        "bump": {"type": "string", "enum": ["major", "minor", "patch", "none"]},
        "findings": findings_schema(),
    },
    "required": ["status", "suggested_version", "bump", "findings"],
}


def build(model, tools, middleware=()):
    return make(model, tools, "release.md", SCHEMA, "release", middleware)
