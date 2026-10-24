from types import SimpleNamespace

from review.evals import (
    EVALUATORS,
    agent_tag_id,
    decisions_passed,
    example_id,
    experiment_prefix,
    finding_files,
    finding_groundedness,
    interface_status,
    release_status,
    security_status,
    suggested_version,
    sync_dataset,
    tag_dataset,
)


def _pair(outputs, expected):
    return SimpleNamespace(outputs=outputs), SimpleNamespace(outputs=expected)


def test_status_fields_are_exact():
    checks = (
        (interface_status, "interface_status", "pass", "fail"),
        (security_status, "security_status", "pass", "fail"),
        (release_status, "release_status", "ready", "not ready"),
        (suggested_version, "suggested_version", "v1.2.0", "v1.3.0"),
    )
    for evaluator, key, good, bad in checks:
        run, example = _pair({key: good}, {key: good})
        assert evaluator(run, example)["score"] == 1
        run, example = _pair({key: bad}, {key: good})
        assert evaluator(run, example)["score"] == 0


def test_finding_files_matches_the_set():
    run, example = _pair(
        {
            "interface_findings": [{"filename": "README.md", "finding": "missing"}],
            "security_findings": [{"filename": "main.tf", "finding": "public"}],
            "release_findings": [{"filename": "README.md", "finding": "again"}],
        },
        {"finding_files": ["README.md", "main.tf"]},
    )
    assert finding_files(run, example)["score"] == 1
    run, example = _pair(
        {"release_findings": [{"filename": "CHANGELOG.md", "finding": "stale"}]},
        {"finding_files": ["README.md"]},
    )
    assert finding_files(run, example)["score"] == 0


_TAGS = [
    {
        "key": "Agent",
        "values": [{"value": "terraform-module-review", "id": "tag-1"}],
    }
]


def _decision(outputs, expected):
    return _pair(
        {
            "interface_status": "pass",
            "security_status": "pass",
            "release_status": "ready",
            "suggested_version": "v1.0.0",
            **outputs,
        },
        {
            "interface_status": "pass",
            "security_status": "pass",
            "release_status": "ready",
            "suggested_version": "v1.0.0",
            "finding_files": [],
            **expected,
        },
    )


def test_decisions_passed_is_the_fraction_of_matching_rows():
    good_run, good_example = _decision({}, {})
    bad_run, bad_example = _decision({"release_status": "not ready"}, {})
    result = decisions_passed([good_run, bad_run], [good_example, bad_example])
    assert result == {"key": "decisions_passed", "score": 0.5, "comment": "1 of 2"}
    empty = decisions_passed([], [])
    assert empty["score"] == 0


class _Grade:
    def __init__(self, body):
        self.body = body
        self.messages = None

    def invoke(self, messages):
        self.messages = messages
        return self.body


def test_finding_groundedness_returns_the_judge_score():
    grade = _Grade({"score": 0, "reason": "The changelog heading is in the file."})
    run, example = _pair(
        {"release_findings": [{"filename": "CHANGELOG.md", "finding": "heading missing"}]},
        {},
    )
    example.inputs = {
        "ref": "latest",
        "compares": {"v1.0.0...latest": "no changes"},
        "files": {"latest": {"CHANGELOG.md": "## 1.0.1\n"}},
    }
    result = finding_groundedness(run, example, grade=grade)
    assert result["key"] == "finding_groundedness"
    assert result["score"] == 0
    assert result["comment"] == "The changelog heading is in the file."
    text = grade.messages[1]["content"]
    assert "heading missing" in text
    assert "## 1.0.1" in text
    assert "groundedness" in grade.messages[0]["content"] or "Score 1" in grade.messages[0]["content"]


def test_finding_groundedness_drops_a_score_that_is_not_0_or_1():
    run, example = _pair({}, {})
    example.inputs = {}
    result = finding_groundedness(run, example, grade=_Grade({"score": 5, "reason": "unsure"}))
    assert result["score"] == 0
    assert result["comment"] == "unsure"


def test_agent_tag_id_matches_the_project_name():
    assert agent_tag_id(_TAGS, "terraform-module-review") == "tag-1"
    try:
        agent_tag_id(_TAGS, "other-agent")
    except RuntimeError as error:
        assert "other-agent" in str(error)
    else:
        raise AssertionError("expected a missing agent tag to raise")


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _Cloud:
    def __init__(self, exists=False, resource_tags=None, examples=None):
        self.exists = exists
        self.resource_tags = resource_tags or []
        self.examples = examples or []
        self.created = None
        self.description = None
        self.calls = []
        self.deleted = []
        self.uploaded = []
        self.updated = []

    def has_dataset(self, dataset_name):
        return self.exists

    def create_dataset(self, name, description=None, tag_value_ids=None):
        self.created = (name, tag_value_ids)
        self.description = description
        return SimpleNamespace(id="new-id")

    def read_dataset(self, dataset_name):
        return SimpleNamespace(id="old-id")

    def list_examples(self, dataset_name):
        return self.examples

    def delete_examples(self, ids):
        self.deleted.extend(ids)

    def create_examples(self, dataset_name, examples):
        self.uploaded.extend(examples)

    def update_examples(self, dataset_name=None, updates=None, **kwargs):
        self.updated.extend(updates or [])

    def request_with_retries(self, method, pathname, **kwargs):
        self.calls.append((method, pathname, kwargs))
        if method == "GET" and pathname.endswith("/tags"):
            return _Response(_TAGS)
        if method == "GET" and pathname.endswith("/tags/resource"):
            return _Response(self.resource_tags)
        return _Response({})


def test_sync_tags_a_new_dataset(monkeypatch):
    monkeypatch.setenv("LANGSMITH_PROJECT", "terraform-module-review")
    client = _Cloud()
    sync_dataset(client, [], "Frozen modules.")
    assert client.created == ("tf-module-review", ["tag-1"])
    assert client.description == "Frozen modules."
    assert not any(call[0] == "POST" for call in client.calls)


def test_experiment_prefix_includes_the_model():
    assert experiment_prefix("anthropic:claude-haiku-5-5") == (
        "tf-module-review-anthropic:claude-haiku-5-5"
    )


def test_example_id_follows_the_scenario_name():
    assert example_id("docs-match") == example_id("docs-match")
    assert example_id("docs-match") != example_id("public-bucket")


def test_sync_updates_a_known_example_and_drops_a_stranger(monkeypatch):
    monkeypatch.setenv("LANGSMITH_PROJECT", "terraform-module-review")
    kept = example_id("docs-match")
    stranger = example_id("retired")
    client = _Cloud(
        exists=True,
        examples=[SimpleNamespace(id=kept), SimpleNamespace(id=stranger)],
    )
    sync_dataset(
        client,
        [
            {
                "inputs": {"id": "docs-match"},
                "outputs": {"interface_status": "pass"},
                "metadata": {"decision": "nothing to release"},
            }
        ],
    )
    assert client.deleted == [stranger]
    assert client.uploaded == []
    assert client.updated[0]["id"] == kept
    assert client.updated[0]["metadata"]["scenario"] == "docs-match"
    assert client.updated[0]["split"] == "base"


def test_sync_tags_an_existing_dataset(monkeypatch):
    monkeypatch.setenv("LANGSMITH_PROJECT", "terraform-module-review")
    client = _Cloud(exists=True)
    sync_dataset(client, [])
    posts = [call for call in client.calls if call[0] == "POST"]
    assert posts[0][2]["json"] == {
        "tag_value_id": "tag-1",
        "resource_type": "dataset",
        "resource_id": "old-id",
    }


def test_tag_dataset_skips_a_dataset_that_already_has_the_agent():
    client = _Cloud(
        resource_tags=[{"key": "Agent", "values": [{"id": "tag-1", "value": "terraform-module-review"}]}]
    )
    tag_dataset(client, "old-id", "terraform-module-review")
    assert not any(call[0] == "POST" for call in client.calls)


def test_langsmith_experiment():
    from review.evals import run_evaluation

    results = run_evaluation()
    failures = []
    for row in results:
        example_id = (row["example"].inputs or {}).get("id", row["example"].id)
        code_keys = {check.__name__ for check in EVALUATORS}
        for item in row["evaluation_results"]["results"]:
            if item.key not in code_keys:
                continue
            if item.score != 1:
                failures.append(
                    f"{example_id} {item.key}={item.score} outputs={row['run'].outputs}"
                )
        if not (row["run"].outputs):
            failures.append(f"{example_id} produced no outputs")
    assert not failures, "\n".join(failures)
