# Portable Agent Skill Check

Check Agent Skills in a checkout before installing them into Hermes, Pi, or OpenClaw. The CLI reads local files and reports packaging issues without loading a skill into an agent, running scripts, or fetching links.

## Run

With Python 3.12 or later and [uv](https://docs.astral.sh/uv/), install the locked dependencies once. The checker itself runs offline.

```sh
uv sync --locked
uv run --locked --offline python -m portable_agent_skill_check .
uv run --locked --offline python -m portable_agent_skill_check ./skills/release-evidence-review --format json
uv run --locked --offline python -m portable_agent_skill_check /path/to/skills --collection
```

By default, a directory containing `SKILL.md` is checked as a single skill. A repository with a `skills/` directory is checked as a collection. A directory with neither reports a missing entrypoint. Use `--collection` for another collection layout. The scan checks each immediate, non-hidden skill directory and its contents. Pass an individual skill directory when a collection has categories or another nesting convention.

## What it checks

- `SKILL.md` has YAML frontmatter, a matching directory name, a nonblank description of at most 1024 characters, and Markdown instructions. Names use the conservative ASCII subset of the [Agent Skills specification](https://agentskills.io/specification), up to 64 lowercase letters, digits, and single separators.
- Local CommonMark links and images in `.md` and `.markdown` files point to regular files inside the same skill. Paths are relative to the containing Markdown file and compared with exact case. External HTTP(S) and mail links, query parameters, and heading fragments are left to the reader.
- Symlinks and junctions are rejected without opening their targets, including links within the same skill. Files are checked from a stable checkout. Changes to the tree during a scan are outside the checker’s scope.
- The parser accepts Markdown files up to 1 MiB. It examines rendered CommonMark destinations. Inline code, fenced examples, plain-text paths, HTML attributes, and unused link definitions are outside its scope.

## Output

The exit code is `0` for a clean scan, `1` for findings including unreadable or missing input, and `2` for invalid command syntax. JSON output contains `valid`, `skills_checked`, and a sorted `diagnostics` list. Each diagnostic has a relative `path`, a `line` or `null`, a `code`, and a `message`. Link line numbers point to the containing Markdown block.

A passing result covers this static subset. Runtime loading, tool availability, optional metadata behavior, permissions, and instruction safety need their own review. Consult the target runtime’s documentation before installation. [Hermes skills](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills) · [Pi skills](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/skills.md) · [OpenClaw skills](https://docs.openclaw.ai/tools/skills)

The bundled sample reviews supplied proof without taking external action. [Release evidence review skill](skills/release-evidence-review/SKILL.md)

For a release involving agent actions, collect evidence about approval, recovery, and ongoing operation. [Fnctn’s production AI integration checklist](https://fnctn.io/notes/production-ai-integration-checklist/)

```sh
uv run --locked --offline python -m pytest -q
```
