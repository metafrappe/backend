#!/usr/bin/env python3
"""Check security advisory decision records (G-142).

Usage: python3 -I advisory_records.py [records-folder]

Each record is one JSON file in advisories/records/. The command prints every problem
and exits with 1 when a record is incomplete. Python standard library only.
"""

import datetime
import json
import sys
from pathlib import Path

FOLDER = Path(__file__).resolve().parent / "advisories"

FIELDS = (
    "advisory_id", "component", "severity", "known_exploited", "deployed_version",
    "affected_range", "feature_enabled", "attack_precondition", "fixed_version",
    "decision", "rationale", "evidence", "decided_by", "decided_on",
)
TEXT_FIELDS = (
    "advisory_id", "deployed_version", "affected_range", "attack_precondition",
    "fixed_version", "rationale", "decided_by",
)
CHOICES = {
    "severity": ("low", "medium", "high", "critical"),
    "feature_enabled": ("yes", "no", "not_installed", "unknown"),
    "decision": ("apply_now", "schedule", "not_applicable"),
}
EVIDENCE_FIELDS = ("version", "configuration")


def load_sources(path=FOLDER / "sources.json"):
    """Return the watched sources keyed by component id."""
    return {source["component"]: source for source in json.loads(path.read_text())["sources"]}


def filled(value):
    return isinstance(value, str) and value.strip() != ""


def validate(record, sources=None):
    """Return a list of problems; an empty list means the record is complete."""
    if not isinstance(record, dict):
        return ["record must be a JSON object"]
    sources = load_sources() if sources is None else sources
    errors = [f"missing field: {name}" for name in FIELDS if name not in record]
    errors += [f"unknown field: {name}" for name in record if name not in FIELDS]
    errors += [f"empty field: {name}" for name in TEXT_FIELDS
               if name in record and not filled(record[name])]
    for name, choices in CHOICES.items():
        if name in record and record[name] not in choices:
            errors.append(f"{name} must be one of {', '.join(choices)}")
    if "component" in record and record["component"] not in sources:
        errors.append("component is not on the watched source list")
    if "known_exploited" in record and not isinstance(record["known_exploited"], bool):
        errors.append("known_exploited must be true or false")
    if "decided_on" in record:
        try:
            datetime.date.fromisoformat(str(record["decided_on"]))
        except ValueError:
            errors.append("decided_on must be a YYYY-MM-DD date")
    evidence = record.get("evidence")
    if "evidence" in record and not (
            isinstance(evidence, dict) and set(evidence) == set(EVIDENCE_FIELDS)):
        errors.append("evidence must hold exactly: " + ", ".join(EVIDENCE_FIELDS))
    elif record.get("decision") == "not_applicable":
        errors += [f"not_applicable needs evidence.{name}" for name in EVIDENCE_FIELDS
                   if not filled(evidence.get(name))]
    return errors


def check_folder(folder):
    """Validate every *.json record in a folder; return 'file: problem' lines."""
    sources = load_sources()
    problems, seen = [], {}
    for path in sorted(Path(folder).glob("*.json")):
        try:
            record = json.loads(path.read_text())
        except (OSError, ValueError) as error:
            problems.append(f"{path.name}: cannot read JSON: {error}")
            continue
        problems += [f"{path.name}: {error}" for error in validate(record, sources)]
        if isinstance(record, dict):
            key = (record.get("component"), record.get("advisory_id"))
            if key in seen:
                problems.append(f"{path.name}: same advisory as {seen[key]}")
            seen.setdefault(key, path.name)
    return problems


def main(argv):
    folder = Path(argv[1]) if len(argv) > 1 else FOLDER / "records"
    problems = check_folder(folder)
    for line in problems:
        print(line)
    print(f"advisory records: {'fail' if problems else 'pass'}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
