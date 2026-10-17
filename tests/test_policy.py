from release.policy import (
    chosen_release_branch,
    next_version,
    parse_version,
    select_base_ref,
)


def test_parse_version_accepts_exact_release_names():
    assert parse_version("v1.0.1") == (1, 0, 1)
    assert parse_version(" v1.10.0 ") == (1, 10, 0)
    assert parse_version("v0.0.0") == (0, 0, 0)


def test_parse_version_rejects_tags_and_prefixes():
    for name in ("v1.2", "v1.2.3-rc1", "release/verify-v1.0.2", "main", "v01.0.0", "1.0.1"):
        assert parse_version(name) is None


def test_selects_highest_tag_and_ignores_other_names():
    chosen = select_base_ref(
        [
            "refs/tags/v1.0.0",
            "refs/tags/v1.0.1",
            "refs/tags/v1.0.1^{}",
            "refs/tags/v1.2",
            "refs/tags/v1.2.3-rc1",
            "refs/tags/not-a-version",
            "refs/heads/main",
            "refs/remotes/origin/v1.0.1",
        ]
    )
    assert chosen.rev == "v1.0.1"
    assert chosen.short_name == "v1.0.1"
    assert chosen.local is True


def test_numeric_order_not_lexicographic():
    chosen = select_base_ref(
        [
            "refs/tags/v1.9.0",
            "refs/tags/v1.10.0",
            "refs/tags/v2.0.0",
        ]
    )
    assert chosen.short_name == "v2.0.0"


def test_next_version_from_v1_0_1():
    base = (1, 0, 1)
    assert next_version(base, "major") == "v2.0.0"
    assert next_version(base, "minor") == "v1.1.0"
    assert next_version(base, "patch") == "v1.0.2"
    assert next_version(base, "none") == ""


def test_release_branch_choices():
    assert chosen_release_branch("rejected", "v1.1.0", "") == ("rejected", "")
    assert chosen_release_branch("nope", "v1.1.0", "") == ("rejected", "")
    assert chosen_release_branch("approved", "v1.1.0", "") == ("release", "v1.1.0")
    assert chosen_release_branch("approved", "", "") == ("release", "")
    assert chosen_release_branch("approved", "v1.2", "") == ("invalid_version", "v1.2")
    assert chosen_release_branch("edited", "v1.1.0", " v1.4.0 ") == ("release", "v1.4.0")
    assert chosen_release_branch("edited", "v1.1.0", "v1.2.3-rc1") == ("invalid_version", "v1.2.3-rc1")


def test_missing_version_refs():
    try:
        select_base_ref(["refs/heads/main", "refs/tags/feature-update"])
    except LookupError:
        return
    raise AssertionError("expected LookupError")
