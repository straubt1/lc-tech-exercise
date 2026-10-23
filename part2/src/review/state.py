from typing import TypedDict


class Finding(TypedDict):
    filename: str
    finding: str


class ProposedFile(TypedDict):
    filename: str
    content: str


class State(TypedDict, total=False):
    repo: str
    ref: str
    error: str
    interface_status: str
    interface_findings: list[Finding]
    security_status: str
    security_findings: list[Finding]
    release_status: str
    release_findings: list[Finding]
    current_version: str
    suggested_version: str
    bump: str
    suggestions: str
    proposed_files: list[ProposedFile]
    pr_title: str
    pr_body: str
    decision: str
    pr_url: str
