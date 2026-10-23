from types import SimpleNamespace

from review.evals import (
    finding_files,
    interface_status,
    release_status,
    security_status,
    suggested_version,
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


def test_langsmith_experiment():
    from review.evals import run_evaluation

    results = run_evaluation()
    failures = []
    for row in results:
        example_id = (row["example"].inputs or {}).get("id", row["example"].id)
        for item in row["evaluation_results"]["results"]:
            if item.score != 1:
                failures.append(
                    f"{example_id} {item.key}={item.score} outputs={row['run'].outputs}"
                )
        if not (row["run"].outputs):
            failures.append(f"{example_id} produced no outputs")
    assert not failures, "\n".join(failures)
