from pathlib import Path
import json
import subprocess
import sys

import pytest

from portable_agent_skill_check.check import check

ROOT = Path(__file__).resolve().parents[1]


def write_skill(
    directory: Path,
    *,
    name: str | None = None,
    description: str = "Review supplied release evidence.",
    body: str = "# Review\n",
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    file = directory / "SKILL.md"
    file.write_text(
        f"---\nname: {name or directory.name}\ndescription: {description}\n---\n{body}",
        encoding="utf-8",
    )
    return file


def codes(path: Path) -> list[str]:
    return [diagnostic.code for diagnostic in check(path).diagnostics]


def test_bundled_example_passes_as_repository_collection_and_single_skill():
    for path, collection in [
        (ROOT, False),
        (ROOT / "skills", True),
        (ROOT / "skills" / "release-evidence-review", False),
    ]:
        report = check(path, collection=collection)
        assert report.skills_checked == 1
        assert not report.diagnostics


@pytest.mark.parametrize("name", ["Bad", "two--parts", "-leading", "trailing-", "a" * 65, "ümlaut"])
def test_name_must_use_portable_characters_and_length(tmp_path, name):
    folder = tmp_path / "review"
    write_skill(folder, name=name)
    assert codes(folder) == ["name-invalid"]


def test_name_must_match_directory_and_yaml_12_plain_on_is_a_string(tmp_path):
    folder = tmp_path / "on"
    write_skill(folder)
    assert codes(folder) == []
    write_skill(folder, name="different")
    assert codes(folder) == ["name-mismatch"]


@pytest.mark.parametrize("description", ['""', '"   "', "true", "123", "[item]", "x" * 1025])
def test_description_must_be_a_nonblank_string_up_to_the_spec_limit(tmp_path, description):
    folder = tmp_path / "review"
    write_skill(folder, description=description)
    assert codes(folder) == ["description-invalid"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("# Instructions\n", "frontmatter-missing"),
        ("---\nname: review\n", "frontmatter-unclosed"),
        ("---\n- one\n- two\n---\n# Review\n", "frontmatter-type"),
        ("---\nname: review\nname: review\ndescription: Review.\n---\n# Review\n", "frontmatter-invalid"),
        ("---\nname: review\ndescription: !unknown Review.\n---\n# Review\n", "frontmatter-invalid"),
        ("---\nname: review\ndescription: Review.\n---\n", "body-empty"),
    ],
)
def test_frontmatter_and_body_requirements(tmp_path, text, expected):
    folder = tmp_path / "review"
    write_skill(folder).write_text(text, encoding="utf-8")
    assert codes(folder) == [expected]


def test_links_use_commonmark_and_resolve_relative_to_the_markdown_file(tmp_path):
    folder = tmp_path / "review"
    write_skill(folder, body="""# Review

[Guide][guide] and ![Example](assets/example.svg).
[External](https://example.com/%FF) and [Jump](#review).

[guide]: references/Review%20guide.md#section

```markdown
[Illustrative broken path](does-not-exist.md)
```
""")
    (folder / "assets").mkdir()
    (folder / "assets" / "example.svg").write_text("<svg />", encoding="utf-8")
    (folder / "references").mkdir()
    (folder / "references" / "Review guide.md").write_text(
        "[Back](../SKILL.md?mode=review#review)\n", encoding="utf-8",
    )
    assert codes(folder) == []


def test_reference_findings_include_file_block_line_and_kind(tmp_path):
    folder = tmp_path / "review"
    write_skill(folder, body="""# Review

[Missing](no-file.md)

[Outside](%2e%2e/nearby.md)

[Absolute](/absolute.md)

[Local URL](file:///somewhere.md)

[Folder](references/)

[Windows drive](C%3A/absolute.md)
""")
    (folder / "references").mkdir()
    findings = check(folder).diagnostics
    assert [(item.path, item.line, item.code) for item in findings] == [
        ("SKILL.md", 7, "reference-missing"),
        ("SKILL.md", 9, "reference-outside"),
        ("SKILL.md", 11, "reference-nonrelative"),
        ("SKILL.md", 13, "reference-nonrelative"),
        ("SKILL.md", 15, "reference-not-file"),
        ("SKILL.md", 17, "reference-nonrelative"),
    ]


def test_symlinks_are_reported_without_reading_or_listing_targets(tmp_path, monkeypatch):
    folder = tmp_path / "review"
    write_skill(folder, body="[Reference](links/notes.md)\n")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "notes.md").write_bytes(b"\xff")
    try:
        (folder / "links").symlink_to(outside, target_is_directory=True)
        (folder / "pointer.md").symlink_to(outside / "notes.md")
    except (OSError, NotImplementedError):
        pytest.skip("This filesystem cannot create symlinks.")

    original_open = Path.open
    original_iterdir = Path.iterdir

    def checked_open(path, *args, **kwargs):
        assert path == folder / "SKILL.md"
        return original_open(path, *args, **kwargs)

    def checked_iterdir(path):
        assert path == folder
        return original_iterdir(path)

    monkeypatch.setattr(Path, "open", checked_open)
    monkeypatch.setattr(Path, "iterdir", checked_iterdir)
    findings = check(folder).diagnostics
    assert [(item.path, item.code) for item in findings] == [
        ("SKILL.md", "reference-symlink"), ("links", "symlink"), ("pointer.md", "symlink"),
    ]


def test_repository_collection_reports_missing_skills_and_skill_file_symlink(tmp_path):
    write_skill(tmp_path / "skills" / "one")
    (tmp_path / "skills" / "two").mkdir()
    replacement = tmp_path / "skills" / "three"
    replacement.mkdir()
    try:
        (replacement / "SKILL.md").symlink_to(tmp_path / "skills" / "one" / "SKILL.md")
    except (OSError, NotImplementedError):
        pytest.skip("This filesystem cannot create symlinks.")
    report = check(tmp_path)
    assert report.skills_checked == 3
    assert [(item.path, item.code) for item in report.diagnostics] == [
        ("skills/three/SKILL.md", "symlink"), ("skills/two/SKILL.md", "skill-missing"),
    ]


def test_bad_encoding_and_missing_input_are_diagnostics(tmp_path):
    folder = tmp_path / "review"
    write_skill(folder).write_bytes(b"\xff")
    assert codes(folder) == ["markdown-encoding"]
    assert codes(tmp_path / "missing") == ["input-directory"]


def test_missing_skill_root_does_not_scan_unrelated_files(tmp_path):
    (tmp_path / "notes.md").write_text("[Broken](absent.md)", encoding="utf-8")
    report = check(tmp_path)
    assert report.skills_checked == 0
    assert [item.code for item in report.diagnostics] == ["skill-missing"]


def test_cli_json_is_deterministic_and_has_distinct_usage_exit_code(tmp_path):
    folder = tmp_path / "review"
    write_skill(folder, body="[Missing](no-file.md)\n")
    command = [sys.executable, "-m", "portable_agent_skill_check", str(folder), "--format", "json"]
    first = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    second = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    assert first.returncode == second.returncode == 1
    assert first.stdout == second.stdout
    assert not first.stderr
    result = json.loads(first.stdout)
    assert result["valid"] is False
    assert result["skills_checked"] == 1
    assert result["diagnostics"][0]["path"] == "SKILL.md"
    assert result["diagnostics"][0]["code"] == "reference-missing"

    usage = subprocess.run(
        [sys.executable, "-m", "portable_agent_skill_check", "--format", "invalid"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert usage.returncode == 2
