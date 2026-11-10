import argparse
from dataclasses import asdict
import json
from pathlib import Path

from .check import check


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Agent Skills without installing or running them.")
    parser.add_argument("path", nargs="?", type=Path, default=Path("."), help="A skill or a repository with skills/")
    parser.add_argument("--collection", action="store_true", help="Check immediate skill directories in PATH")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()

    report = check(args.path, collection=args.collection)
    valid = not report.diagnostics
    if args.format == "json":
        print(json.dumps({
            "valid": valid,
            "skills_checked": report.skills_checked,
            "diagnostics": [asdict(item) for item in report.diagnostics],
        }, indent=2))
    else:
        for item in report.diagnostics:
            location = f"{item.path}:{item.line}" if item.line is not None else item.path
            print(f"{location}: {item.code}: {item.message}")
        print(f"Checked {report.skills_checked} skill(s). {len(report.diagnostics)} finding(s).")
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
