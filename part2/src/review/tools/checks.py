import subprocess

from langchain.tools import tool

from review.reader import Reader


def run_command(argv: list[str]) -> str:
    try:
        completed = subprocess.run(argv, capture_output=True, text=True, timeout=120)
    except FileNotFoundError:
        return f"{argv[0]} is not installed"
    except subprocess.TimeoutExpired:
        return f"{argv[0]} timed out"
    text = (completed.stdout or "").strip()
    if text:
        return text
    err = (completed.stderr or "").strip()
    if completed.returncode != 0:
        return err or f"{argv[0]} failed"
    return err or "no output"


def _clip(text: str, limit: int = 48000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...truncated"


def _root(reader: Reader, ref: str) -> str:
    path = reader.checkout(ref)
    if path.startswith("/"):
        return path
    return path or "not found"


def build_interface_tools(reader: Reader, run=run_command):
    @tool
    def terraform_docs(ref: str) -> str:
        """Generate terraform-docs markdown for one git ref.

        Prints the docs in memory and returns the current README.md beside them.
        Does not modify any files.
        """
        path = _root(reader, ref)
        if not path.startswith("/"):
            return path
        docs = run(["terraform-docs", "markdown", "table", "--output-file", "", path])
        readme = reader.read_file("README.md", ref)
        return "\n".join(["generated docs", _clip(docs), "", "README.md", _clip(readme)])

    return [terraform_docs]


def build_security_tools(reader: Reader, run=run_command):
    @tool
    def trivy_config(ref: str) -> str:
        """Run trivy config on the module root for one git ref.

        Returns the full JSON report, including LOW and MEDIUM. Does not filter
        by severity and does not modify any files.
        """
        path = _root(reader, ref)
        if not path.startswith("/"):
            return path
        return _clip(run(["trivy", "config", "--format", "json", "--quiet", path]))

    return [trivy_config]


def build_release_tools(held: dict):
    @tool
    def get_last_release_tag() -> str:
        """Return the latest published release tag already loaded for this run.

        Empty when the repo has no release tag.
        """
        tags = held.get("release_tags") or []
        return tags[0] if tags else ""

    @tool
    def get_diff_since_last_release() -> str:
        """Return the diff from the latest release tag to the candidate ref, plus CHANGELOG.md.

        The changelog is the file at the candidate ref, already loaded for this run.
        An unchanged changelog is absent from the diff and is still included here.
        Says there is no prior release when the repo has no tag.
        """
        tags = held.get("release_tags") or []
        diff = "No prior release." if not tags else (held.get("diff") or "")
        changelog = _clip(held.get("changelog") or "")
        return "\n".join(["diff", diff, "", "CHANGELOG.md", changelog])

    return [get_last_release_tag, get_diff_since_last_release]
