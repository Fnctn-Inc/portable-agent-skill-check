from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path, PurePosixPath
import re
import stat
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
MAX_MARKDOWN_BYTES = 1024 * 1024
SKILL_FILE = PurePosixPath("SKILL.md")
MARKDOWN = MarkdownIt("commonmark", {"html": False})
# Keep destinations that would be rejected for rendering so the linter can report them.
MARKDOWN.validateLink = lambda _destination: True


@dataclass(frozen=True)
class Diagnostic:
    path: str
    line: int | None
    code: str
    message: str


@dataclass
class Report:
    skills_checked: int = 0
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def add(self, path: PurePosixPath, code: str, message: str, line: int | None = None) -> None:
        self.diagnostics.append(Diagnostic(path.as_posix(), line, code, message))


def entry_kind(path: Path) -> str:
    entry = path.lstat()
    if stat.S_ISLNK(entry.st_mode) or (
        getattr(entry, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    ):
        return "link"
    if stat.S_ISDIR(entry.st_mode):
        return "directory"
    if stat.S_ISREG(entry.st_mode):
        return "file"
    return "special"


def list_directory(path: Path, label: PurePosixPath, report: Report) -> list[Path]:
    try:
        return sorted(path.iterdir(), key=lambda entry: entry.name)
    except OSError:
        report.add(label, "directory-unreadable", "The directory could not be listed.")
        return []


def inspect_entry(path: Path, label: PurePosixPath, report: Report) -> str | None:
    try:
        kind = entry_kind(path)
    except OSError:
        report.add(label, "entry-unreadable", "The filesystem entry could not be inspected.")
        return None

    if kind == "link":
        report.add(label, "symlink", "Symlinks and junctions are outside this portable subset.")
    elif kind == "special":
        report.add(label, "special-file", "Use a regular file or directory.")
    return kind


def index_skill(root: Path, prefix: PurePosixPath, report: Report) -> dict[PurePosixPath, str]:
    entries: dict[PurePosixPath, str] = {}
    directories = [root]
    while directories:
        directory = directories.pop()
        for entry in list_directory(directory, prefix / directory.relative_to(root).as_posix(), report):
            relative = PurePosixPath(entry.relative_to(root).as_posix())
            kind = inspect_entry(entry, prefix / relative, report)
            if kind is not None:
                entries[relative] = kind
            if kind == "directory":
                directories.append(entry)
    return entries


def read_markdown(path: Path, label: PurePosixPath, report: Report) -> str | None:
    try:
        with path.open("rb") as source:
            content = source.read(MAX_MARKDOWN_BYTES + 1)
    except OSError:
        report.add(label, "markdown-unreadable", "The Markdown file could not be read.")
        return None
    if len(content) > MAX_MARKDOWN_BYTES:
        report.add(label, "markdown-too-large", "The Markdown file exceeds the 1 MiB check limit.")
        return None
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        report.add(label, "markdown-encoding", "Save the Markdown file as UTF-8.")
        return None


def check_frontmatter(text: str, directory_name: str, label: PurePosixPath, report: Report) -> tuple[str, int]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip() != "---":
        report.add(label, "frontmatter-missing", "Begin SKILL.md with a YAML frontmatter delimiter.", 1)
        return text, 0
    end = next((index for index, line in enumerate(lines[1:], 1) if line.rstrip() == "---"), None)
    if end is None:
        report.add(label, "frontmatter-unclosed", "Close YAML frontmatter with a second delimiter.", 1)
        return "", 0

    yaml = YAML(typ="safe", pure=True)
    yaml.allow_duplicate_keys = False
    yaml.max_depth = 32
    try:
        metadata = yaml.load("".join(lines[1:end]))
    except (YAMLError, RecursionError) as error:
        mark = getattr(error, "problem_mark", None)
        report.add(
            label, "frontmatter-invalid", "Use valid YAML with unique keys.",
            mark.line + 2 if mark is not None else 1,
        )
    else:
        if not isinstance(metadata, dict):
            report.add(label, "frontmatter-type", "Frontmatter must be a YAML mapping.", 1)
        else:
            name = metadata.get("name")
            if not isinstance(name, str) or len(name) > 64 or NAME.fullmatch(name) is None:
                report.add(
                    label, "name-invalid",
                    "Use 1–64 lowercase ASCII letters, digits, or single hyphens between segments.", 1,
                )
            elif name != directory_name:
                report.add(label, "name-mismatch", "The name must match the skill directory.", 1)

            description = metadata.get("description")
            if not isinstance(description, str) or not description.strip() or len(description) > 1024:
                report.add(label, "description-invalid", "Use a nonblank string of at most 1024 characters.", 1)

    body = "".join(lines[end + 1:])
    if not body.strip():
        report.add(label, "body-empty", "Provide Markdown instructions after the frontmatter.", end + 1)
    return body, end + 1


def target_path(destination: str, source: PurePosixPath) -> tuple[PurePosixPath | None, str | None]:
    try:
        url = urlsplit(destination)
    except ValueError:
        return None, "reference-invalid"

    if url.scheme in {"http", "https", "mailto"}:
        return None, None
    try:
        path = unquote(url.path, errors="strict")
    except UnicodeDecodeError:
        return None, "reference-invalid"
    if url.scheme or url.netloc or path.startswith("/") or "\\" in path or re.match(r"[a-zA-Z]:", path):
        return None, "reference-nonrelative"
    if any(ord(character) < 32 or ord(character) == 127 for character in path):
        return None, "reference-invalid"
    if not path:
        return None, None

    parts = list(source.parent.parts)
    for part in PurePosixPath(path).parts:
        if part == "..":
            if not parts:
                return None, "reference-outside"
            parts.pop()
        else:
            parts.append(part)
    return PurePosixPath(*parts), None


REFERENCE_MESSAGES = {
    "reference-invalid": "The Markdown link has an invalid destination.",
    "reference-nonrelative": "Use a relative local file path or an HTTP(S) or mail link.",
    "reference-outside": "The local reference leaves the skill directory.",
    "reference-symlink": "The local reference points through a symlink or junction.",
    "reference-missing": "The local reference does not exist in the skill directory.",
    "reference-not-file": "The local reference must point to a regular file.",
}


def check_links(
    body: str,
    line_offset: int,
    source: PurePosixPath,
    label: PurePosixPath,
    entries: dict[PurePosixPath, str],
    report: Report,
) -> None:
    for block in MARKDOWN.parse(body):
        if not block.children or block.map is None:
            continue
        for inline in block.children:
            attribute = {"link_open": "href", "image": "src"}.get(inline.type)
            destination = inline.attrGet(attribute) if attribute else None
            if not isinstance(destination, str):
                continue
            target, error = target_path(destination, source)
            if target is not None:
                if any(entries.get(part) == "link" for part in (target, *target.parents)):
                    error = "reference-symlink"
                elif target != PurePosixPath(".") and target not in entries:
                    error = "reference-missing"
                elif entries.get(target) != "file":
                    error = "reference-not-file"
            if error:
                report.add(
                    label, error, f"{REFERENCE_MESSAGES[error]} Destination: {destination!r}.",
                    line_offset + block.map[0] + 1,
                )


def check_skill(root: Path, prefix: PurePosixPath, report: Report) -> None:
    report.skills_checked += 1
    entries = index_skill(root, prefix, report)
    entry = entries.get(SKILL_FILE)
    if entry is None:
        report.add(prefix / SKILL_FILE, "skill-missing", "The skill requires a SKILL.md file.")
    elif entry == "directory":
        report.add(prefix / SKILL_FILE, "skill-not-file", "SKILL.md must be a regular file.")

    for relative, kind in entries.items():
        if kind != "file" or relative.suffix.lower() not in {".md", ".markdown"}:
            continue
        label = prefix / relative
        text = read_markdown(root / relative, label, report)
        if text is None:
            continue
        body, offset = (
            check_frontmatter(text, root.name, label, report) if relative == SKILL_FILE else (text, 0)
        )
        check_links(body, offset, relative, label, entries, report)


def check_collection(root: Path, prefix: PurePosixPath, report: Report) -> None:
    for entry in list_directory(root, prefix, report):
        if entry.name.startswith("."):
            continue
        label = prefix / entry.name
        if inspect_entry(entry, label, report) == "directory":
            check_skill(entry, label, report)
    if not report.skills_checked and not report.diagnostics:
        report.add(prefix, "collection-empty", "The collection has no skill directories.")


def kind_if_present(path: Path) -> str | None:
    try:
        return entry_kind(path)
    except FileNotFoundError:
        return None
    except OSError:
        return "unreadable"


def check(path: Path, *, collection: bool = False) -> Report:
    root = Path(os.path.abspath(path))
    prefix = PurePosixPath(".")
    report = Report()
    kind = kind_if_present(root)
    if kind == "link":
        inspect_entry(root, prefix, report)
    elif kind != "directory":
        report.add(prefix, "input-directory", "Choose a readable directory to check.")
    elif collection:
        check_collection(root, prefix, report)
    elif kind_if_present(root / "SKILL.md") is not None:
        check_skill(root, prefix, report)
    elif kind_if_present(root / "skills") is not None:
        directory = root / "skills"
        label = prefix / "skills"
        kind = inspect_entry(directory, label, report)
        if kind == "directory":
            check_collection(directory, label, report)
        elif kind == "file":
            report.add(label, "collection-directory", "The skills collection must be a directory.")
    else:
        report.add(SKILL_FILE, "skill-missing", "No SKILL.md or skills/ collection was found.")
    report.diagnostics.sort(key=lambda item: (item.path, item.line or 0, item.code, item.message))
    return report
