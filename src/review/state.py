from typing import TypedDict


class Finding(TypedDict):
    filename: str
    finding: str


class ProposedFile(TypedDict):
    filename: str
    content: str


class FoundVersion(TypedDict):
    version: str
    published: bool
    source: str


class State(TypedDict, total=False):
    repo: str
    ref: str
    error: str
    review_status: str
    review_findings: list[Finding]
    suggested_version: str
    bump: str
    justification: str
    versions: list[FoundVersion]
    version_findings: list[Finding]
    suggestions: str
    proposed_files: list[ProposedFile]
    decision: str
    pr_url: str
