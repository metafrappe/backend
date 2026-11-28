#!/usr/bin/env python3
"""Fail the naming gate only for findings that are not in the reviewed baseline.

check_names.py reports every old finding too (AJA-1588). The reviewed old findings are listed in
baseline.json. A finding is matched by path, rule and message, not by line, so editing a file
above an old finding does not fail the gate. A second copy of a known finding is new.

The gate also fails in two more cases (AJA-1721):
- The baseline grew. CI passes the target commit with --base-ref and reads the target baseline
  with git from that commit. A pull request may only shrink the baseline.
- A baseline finding is fixed but still listed. Otherwise a later finding at the same place would
  take its slot and stay hidden. Remove fixed findings in the same change.

Shrink the baseline after a fix: python3.14 -B dev/naming/check_new_names.py --update
--update writes every current finding, so review the diff: it must only remove or lower entries.
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
BASELINE_PATH = "dev/naming/baseline.json"


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


def parse_baseline(text, source):
    entries = json.loads(text)
    if not isinstance(entries, list):
        raise ValueError(f"{source} must hold a JSON list")
    allowed = Counter()
    for entry in entries:
        if (
            not isinstance(entry, dict)
            or set(entry) != {"path", "rule", "message", "count"}
            or not isinstance(entry["count"], int)
            or entry["count"] < 1
            or key(entry) in allowed
        ):
            raise ValueError(f"{source} has a bad entry: {entry}")
        allowed[key(entry)] = entry["count"]
    return allowed


def read_baseline(path):
    return parse_baseline(path.read_text(encoding="utf-8"), path)


def git(root, *arguments):
    return subprocess.run(
        ["git", "-C", str(root), *arguments], capture_output=True, text=True, check=False
    )


def read_base_ref(root, ref):
    """Return the baseline of the target commit, or None if that commit has no baseline yet."""
    if not ref or ref.startswith("-"):
        raise ValueError(f"bad target commit: {ref!r}")
    if git(root, "cat-file", "-e", f"{ref}^{{commit}}").returncode != 0:
        raise ValueError(f"target commit {ref} is not in this checkout")
    if git(root, "cat-file", "-e", f"{ref}:{BASELINE_PATH}").returncode != 0:
        return None
    shown = git(root, "show", f"{ref}:{BASELINE_PATH}")
    if shown.returncode != 0:
        raise ValueError(f"git could not read {BASELINE_PATH} at {ref}: {shown.stderr.strip()}")
    return parse_baseline(shown.stdout, f"{BASELINE_PATH} at {ref}")


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
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--base-ref", help="Target commit. Its baseline is read with git; ours must not grow.")
    target.add_argument("--base-baseline", type=Path, help="Target baseline file; ours must not grow.")
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
        base = None
        if arguments.base_baseline:
            base = read_baseline(arguments.base_baseline)
        elif arguments.base_ref:
            base = read_base_ref(arguments.root, arguments.base_ref)
            if base is None:
                print(f"The target commit has no baseline at {BASELINE_PATH}. The growth check is skipped.")
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Naming gate could not finish: {error}", file=sys.stderr)
        return 2

    current = Counter(key(finding) for finding in findings)
    new = current - allowed
    fixed = allowed - current
    grown = allowed - base if base is not None else Counter()
    for item in sorted(grown):
        print(
            f"Error: the baseline grew: {item[0]} [{item[1]}] {item[2]} allows {allowed[item]}, "
            f"the target branch allows {base[item]}"
        )
    if grown:
        print("A pull request may only shrink the baseline. Fix the finding or rename it instead.")
    for item in sorted(new):
        lines = sorted(finding["line"] for finding in findings if key(finding) == item)
        places = ", ".join(f"{item[0]}:{line}" for line in lines)
        print(f"Error: new naming finding [{item[1]}] {item[2]} at {places}")
    for item in sorted(fixed):
        print(f"Error: fixed finding still in the baseline: {item[0]} [{item[1]}] {item[2]}")
    if fixed:
        print(
            "Shrink the baseline: run check_new_names.py --update and commit the smaller baseline. "
            "A fixed finding left in the list would hide a new finding at the same place."
        )
    print(
        f"{len(findings)} findings, {sum(allowed.values())} in the baseline, "
        f"{sum(new.values())} new, {sum(fixed.values())} fixed, {sum(grown.values())} grown."
    )
    return 1 if new or fixed or grown else 0


if __name__ == "__main__":
    raise SystemExit(main())
