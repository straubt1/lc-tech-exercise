from types import SimpleNamespace

from review.evals import finding_files, review_status, suggested_version, versions


def _pair(outputs, expected):
    return SimpleNamespace(outputs=outputs), SimpleNamespace(outputs=expected)


def test_review_status_is_exact():
    run, example = _pair({"review_status": "pass"}, {"review_status": "pass"})
    assert review_status(run, example)["score"] == 1
    run, example = _pair({"review_status": "fail"}, {"review_status": "pass"})
    assert review_status(run, example)["score"] == 0


def test_suggested_version_is_exact():
    run, example = _pair({"suggested_version": "v1.2.0"}, {"suggested_version": "v1.2.0"})
    assert suggested_version(run, example)["score"] == 1
    run, example = _pair({"suggested_version": "v1.3.0"}, {"suggested_version": "v1.2.0"})
    assert suggested_version(run, example)["score"] == 0


def test_finding_files_matches_the_set():
    run, example = _pair(
        {
            "review_findings": [{"filename": "README.md", "finding": "missing"}],
            "version_findings": [{"filename": "README.md", "finding": "again"}],
        },
        {"finding_files": ["README.md"]},
    )
    assert finding_files(run, example)["score"] == 1
    run, example = _pair(
        {"review_findings": [{"filename": "CHANGELOG.md", "finding": "stale"}]},
        {"finding_files": ["README.md"]},
    )
    assert finding_files(run, example)["score"] == 0


def test_versions_match_published_pairs():
    run, example = _pair(
        {"versions": [{"version": "v1.2.0", "published": False, "source": "CHANGELOG.md"}]},
        {"versions": [{"version": "v1.2.0", "published": False}]},
    )
    assert versions(run, example)["score"] == 1
    run, example = _pair(
        {"versions": [{"version": "v1.2.0", "published": True, "source": "tag"}]},
        {"versions": [{"version": "v1.2.0", "published": False}]},
    )
    assert versions(run, example)["score"] == 0


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
