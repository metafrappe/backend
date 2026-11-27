#!/usr/bin/env python3
"""Fail the naming gate only for findings that are not in the reviewed baseline.

check_names.py reports every old finding too (AJA-1588). The reviewed old findings are listed in
baseline.json. A finding is matched by path, rule and message, not by line, so editing a file
above an old finding does not fail the gate. A second copy of a known finding is new.

Update the baseline only after review: python3.14 -B dev/naming/check_new_names.py --update
"""

import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASELINE = HERE / "baseline.json"
CHECK_NAMES = HERE / "check_names.py"


def key(finding):
    return finding["path"], finding["rule"], finding["message"]


def scan(root):
    process = subprocess.run(
        [sys.executable, "-B", str(CHECK_NAMES), "--root", str(root), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    sys.stderr.write(process.stderr)
    if process.returncode not in (0, 1):
        raise RuntimeError(f"check_names.py stopped with exit code {process.returncode}")
    return json.loads(process.stdout)


def read_baseline(path):
    entries = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(entries, list):
        raise ValueError(f"{path} must hold a JSON list")
    allowed = Counter()
    for entry in entries:
        if set(entry) != {"path", "rule", "message", "count"} or entry["count"] < 1:
            raise ValueError(f"{path} has a bad entry: {entry}")
        allowed[key(entry)] = entry["count"]
    return allowed


def write_baseline(path, findings):
    # The branch name depends on the local checkout. CI checks out a detached commit.
    findings = [finding for finding in findings if finding["rule"] != "branch-name"]
    counts = Counter(key(finding) for finding in findings)
    entries = [
        {"path": item[0], "rule": item[1], "message": item[2], "count": count}
        for item, count in sorted(counts.items())
    ]
    lines = ",\n".join(json.dumps(entry, ensure_ascii=False) for entry in entries)
    path.write_text(f"[\n{lines}\n]\n" if entries else "[]\n", encoding="utf-8")
    return len(findings)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--baseline", type=Path, default=BASELINE)
    parser.add_argument("--findings", type=Path, help="Read check_names.py --json output instead of scanning.")
    parser.add_argument("--update", action="store_true", help="Write every current finding to the baseline.")
    arguments = parser.parse_args()
    try:
        if arguments.findings:
            findings = json.loads(arguments.findings.read_text(encoding="utf-8"))
        else:
            findings = scan(arguments.root)
        if arguments.update:
            count = write_baseline(arguments.baseline, findings)
            print(f"Wrote {count} findings to {arguments.baseline}.")
            return 0
        allowed = read_baseline(arguments.baseline)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Naming gate could not finish: {error}", file=sys.stderr)
        return 2

    current = Counter(key(finding) for finding in findings)
    new = current - allowed
    fixed = allowed - current
    for item in sorted(new):
        lines = sorted(finding["line"] for finding in findings if key(finding) == item)
        places = ", ".join(f"{item[0]}:{line}" for line in lines)
        print(f"Error: new naming finding [{item[1]}] {item[2]} at {places}")
    for item in sorted(fixed):
        print(f"Fixed: {item[0]} [{item[1]}] {item[2]}")
    if fixed:
        print("Some baseline findings are gone. Run check_new_names.py --update and commit the baseline.")
    print(
        f"{len(findings)} findings, {sum(allowed.values())} in the baseline, "
        f"{sum(new.values())} new, {sum(fixed.values())} fixed."
    )
    return 1 if new else 0


if __name__ == "__main__":
    raise SystemExit(main())
