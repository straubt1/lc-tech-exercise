import subprocess

from langchain.agents.middleware.types import AgentMiddleware
from langchain.tools import tool

from review.reader import Reader

_ALREADY = "Already returned. Use the first result and answer. Do not call this tool again."


def absent(path: str) -> str:
    return f"{path} does not exist at this ref. Do not call read_file again."


def once(seen: set, path: str, text: str, clip: bool = True) -> str:
    """Return one read. A missing file stays missing, and a repeat is not fetched again."""
    if path in seen:
        return _ALREADY
    seen.add(path)
    if str(text).startswith("not found:"):
        return absent(path)
    return _clip(text) if clip else text


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


class HideReadFile(AgentMiddleware):
    """After read_file has answered, the model can no longer call it."""

    tools = ()

    def __init__(self, seen: set):
        self.seen = seen

    def wrap_model_call(self, request, handler):
        return handler(request.override(tools=self._tools(request.tools)))

    async def awrap_model_call(self, request, handler):
        return await handler(request.override(tools=self._tools(request.tools)))

    def _tools(self, tools):
        if not self.seen:
            return tools
        return [tool for tool in tools if _tool_name(tool) != "read_file"]


def build_interface_tools(reader: Reader, run=run_command):
    @tool
    def terraform_docs(ref: str) -> str:
        """Generate terraform-docs markdown for inputs and outputs at one git ref.

        Does not read README.md and does not modify any files.
        """
        path = _root(reader, ref)
        if not path.startswith("/"):
            return path
        docs = run(
            [
                "terraform-docs",
                "markdown",
                "table",
                "--output-file",
                "",
                "--show",
                "inputs",
                "--show",
                "outputs",
                path,
            ]
        )
        return "\n".join(["generated docs", _clip(docs)])

    seen: set[str] = set()

    @tool
    def read_file(path: str, ref: str) -> str:
        """Read README.md at one git ref. Refuses any other path.

        A missing file does not exist. A second call is not fetched again.
        """
        if path != "README.md":
            return "not in this run"
        return once(seen, path, reader.read_file(path, ref))

    return [terraform_docs, read_file], seen


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


def _tool_name(tool) -> str:
    if isinstance(tool, dict):
        return tool.get("name") or ""
    return getattr(tool, "name", "")


def without_called_diff(held: dict, tools: list) -> list:
    """Drop a release tool after it has returned once."""
    drop = set()
    if held.get("diff_read"):
        drop.add("get_diff_since_last_release")
    if held.get("read_paths"):
        drop.add("read_file")
    if not drop:
        return tools
    return [tool for tool in tools if _tool_name(tool) not in drop]


class AnswerAfterDiff(AgentMiddleware):
    """After the diff tool returns, the model can no longer call it."""

    tools = ()

    def __init__(self, held: dict):
        self.held = held

    def wrap_model_call(self, request, handler):
        return handler(request.override(tools=without_called_diff(self.held, request.tools)))

    async def awrap_model_call(self, request, handler):
        return await handler(request.override(tools=without_called_diff(self.held, request.tools)))


def build_release_tools(held: dict, reader: Reader | None = None):
    @tool
    def get_last_release_tag() -> str:
        """Return the latest published release tag already loaded for this run.

        Empty when the repo has no release tag.
        """
        tags = held.get("release_tags") or []
        return tags[0] if tags else ""

    @tool
    def get_diff_since_last_release() -> str:
        """Return the diff from the latest release tag to the candidate ref.

        Does not include CHANGELOG.md. An unchanged changelog is absent from the diff.
        Says there is no prior release when the repo has no tag. A second call does
        not return the diff again.
        """
        if held.get("diff_read"):
            return _ALREADY
        held["diff_read"] = True
        tags = held.get("release_tags") or []
        diff = "No prior release." if not tags else (held.get("diff") or "")
        return "\n".join(["diff", diff])

    seen = held.setdefault("read_paths", set())

    @tool
    def read_file(path: str, ref: str) -> str:
        """Read CHANGELOG.md at one git ref. Refuses any other path.

        A missing file does not exist. A second call is not fetched again.
        """
        if path != "CHANGELOG.md":
            return "not in this run"
        if reader is None:
            text = held.get("changelog") or ""
        else:
            text = reader.read_file(path, ref)
        return once(seen, path, text)

    return [get_last_release_tag, get_diff_since_last_release, read_file]
