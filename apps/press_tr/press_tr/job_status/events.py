"""O-57 status metadata builder; execution data never enters the event."""

EVENT_TYPES = {
	"Agent Job": "press.job_status.changed.v1",
	"Site": "press.job_status.changed.v1",
	"Site Update": "press.job_status.changed.v1",
	"Deploy Candidate Build": "press.deploy_candidate_build.status",
	"New Bench Queue": "press.new_bench_queue.status",
	"Bench": "press.bench.status",
}
DEPLOY_RECORDS = frozenset({"Deploy Candidate Build", "New Bench Queue", "Bench"})
TERMINAL_STATES = {
	"Agent Job": {"Success", "Failure", "Undelivered", "Delivery Failure"},
	"Site": {"Archived"},
	"Site Update": {"Success", "Failure", "Recovered", "Fatal", "Cancelled"},
	"Deploy Candidate Build": {"Success", "Failure"},
	"New Bench Queue": {"Started", "Failure"},
	"Bench": {"Active", "Broken", "Archived"},
}


def build_event(record, previous_status, *, event_id, occurred_at, capture):
	"""Return a changed-state event or None when the status is unchanged."""
	if capture not in {"hook", "reconcile"}:
		raise ValueError("Unknown capture mode")
	record_type = record.get("doctype")
	if record_type not in EVENT_TYPES or record.get("status") == previous_status:
		return None
	if not isinstance(record.get("status"), str) or not record["status"]:
		raise ValueError("Missing record status")
	event = {
		"event_id": event_id,
		"capture": capture,
		"event_type": EVENT_TYPES[record_type],
		"occurred_at": occurred_at,
		"record_type": record_type,
		"record_name": record["name"],
		"old_status": previous_status,
		"new_status": record["status"],
		"team": record.get("team") or None,
		"site": record.get("site") or None,
	}
	if record_type in DEPLOY_RECORDS:
		for field in ("group", "candidate", "deploy"):
			event[field] = record.get(field) or None
	return event


def is_active(record_type, status):
	"""Whether an observed record needs another reconciliation pass."""
	return record_type in EVENT_TYPES and status not in TERMINAL_STATES[record_type]
