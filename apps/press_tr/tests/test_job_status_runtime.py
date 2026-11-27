"""Hook and durable outbox acceptance with a transaction-aware Frappe double."""

import copy
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class Row(dict):
	def __getattr__(self, name):
		return self.get(name)


class Callbacks:
	def __init__(self):
		self.callbacks = []

	def add(self, callback):
		self.callbacks.append(callback)

	def run(self):
		callbacks, self.callbacks = self.callbacks, []
		for callback in callbacks:
			callback()


class FakeDocument(Row):
	def insert(self, **kwargs):
		self["name"] = self.get("state_key") or self.get("event_id") or self.get("name")
		self.fake.rows.setdefault((self.doctype, self.name), self)
		return self

	def save(self, **kwargs):
		self.fake.rows[self.doctype, self.name] = self
		return self


class FakeFrappe(types.ModuleType):
	def __init__(self):
		super().__init__("frappe")
		self.rows = {}
		self.queue = []
		self.logs = []
		self.snapshots = {}
		self.conf = Row()
		self.session = Row(user="Guest")
		self._ = lambda message, **kwargs: message
		self.ValidationError = ValueError
		self.DoesNotExistError = KeyError
		self.db = types.SimpleNamespace(
			after_commit=Callbacks(),
			exists=self.exists,
			get_value=self.get_value,
			set_value=self.set_value,
			commit=lambda: self.db.after_commit.run(),
			savepoint=self.savepoint,
			rollback=self.rollback,
		)

	def savepoint(self, name):
		self.snapshots[name] = {key: dict(row) for key, row in self.rows.items()}

	def rollback(self, save_point=None):
		rows = self.snapshots[save_point or "transaction"]
		self.rows = {}
		for key, value in rows.items():
			self.rows[key] = self.get_doc(value)
		if save_point is None:
			self.db.after_commit.callbacks = []

	def get_doc(self, value, name=None, **kwargs):
		if isinstance(value, dict):
			doc = FakeDocument(value)
			doc.fake = self
			return doc
		return self.rows[value, name]

	def add(self, doctype, name, **fields):
		doc = self.get_doc(dict(doctype=doctype, name=name, **fields))
		self.rows[doctype, name] = doc
		return doc

	def exists(self, doctype, name):
		return (doctype, name) in self.rows

	def get_value(self, doctype, filters, fieldname="name", **kwargs):
		if isinstance(filters, str):
			row = self.rows.get((doctype, filters))
		else:
			row = next(iter(self.get_all(doctype, filters=filters)), None)
		return row.get(fieldname) if row else None

	def set_value(self, doctype, name, field, value=None, **kwargs):
		self.rows[doctype, name].update(field if isinstance(field, dict) else {field: value})

	def get_all(self, doctype, filters=None, pluck=None, **kwargs):
		rows = [
			row
			for (dt, _record_name), row in self.rows.items()
			if dt == doctype and all(row.get(k) == v for k, v in (filters or {}).items())
		]
		return [row[pluck] for row in rows] if pluck else rows

	def enqueue(self, method, **kwargs):
		self.queue.append((method, kwargs))

	def log_error(self, **kwargs):
		self.logs.append(kwargs)

	def throw(self, message, exception=ValueError):
		raise exception(message)


class StatusRuntimeTests(unittest.TestCase):
	def setUp(self):
		self.f = FakeFrappe()
		spec = importlib.util.spec_from_file_location(
			"status_runtime_under_test", ROOT / "press_tr/job_status/runtime.py"
		)
		self.runtime = importlib.util.module_from_spec(spec)
		with patch.dict(sys.modules, {"frappe": self.f}):
			spec.loader.exec_module(self.runtime)

	def events(self):
		return [json.loads(row["payload"]) for row in self.f.get_all("PTR Job Status Outbox")]

	def observe_job(self):
		job = self.f.add("Agent Job", "job-1", status="Running", modified="fixed")
		self.runtime.on_record(job)
		self.f.db.commit()
		self.runtime.reconcile()
		return job

	def test_poll_hook_is_deduplicated_and_preserves_panel_channel(self):
		self.runtime.after_press_job(method="unrelated.worker")
		self.assertEqual(self.f.queue, [])
		self.runtime.after_press_job(method="press.press.doctype.agent_job.agent_job.poll_pending_jobs")
		self.assertEqual(len(self.f.queue), 1)
		_worker, options = self.f.queue[0]
		self.assertTrue(options["deduplicate"])
		self.assertTrue(options["job_id"])
		self.assertNotIn("agent_job_update", str(self.f.queue))

	def test_callback_defers_enqueue_until_commit(self):
		self.f.add("Agent Job", "job-1", status="Running")
		self.runtime.after_callback(Row(agent_job="job-1"))
		self.assertEqual(self.f.queue, [])
		self.f.db.commit()
		self.assertEqual(len(self.f.queue), 1)

	def test_poll_and_callback_same_status_produce_one_event(self):
		job = self.observe_job()
		job["status"] = "Success"
		self.runtime.after_press_job(method="press.press.doctype.agent_job.agent_job.poll_pending_jobs")
		self.runtime.reconcile()
		self.runtime.after_callback(Row(agent_job="job-1"))
		self.f.db.commit()
		self.runtime.reconcile()
		events = [e for e in self.events() if e["new_status"] == "Success"]
		self.assertEqual(len(events), 1)
		self.assertEqual(events[0]["old_status"], "Running")

	def test_fail_old_jobs_without_modified_emits_failure(self):
		job = self.observe_job()
		job["status"] = "Failure"
		self.runtime.reconcile()
		self.assertEqual(self.events()[-1]["new_status"], "Failure")
		self.assertEqual(job["modified"], "fixed")

	def test_linked_site_site_update_and_bench_direct_writes_are_observed(self):
		site = self.f.add("Site", "site-1", status="Pending", team="team-1")
		update = self.f.add("Site Update", "update-1", status="Pending", site="site-1")
		bench = self.f.add("Bench", "bench-1", status="Pending")
		job = self.f.add(
			"Agent Job",
			"job-1",
			status="Running",
			site="site-1",
			bench="bench-1",
			reference_doctype="Site Update",
			reference_name="update-1",
		)
		self.runtime.on_record(job)
		self.runtime.reconcile()
		site["status"], update["status"], bench["status"] = "Active", "Success", "Installing"
		self.runtime.reconcile()
		self.assertTrue(
			{("Site", "Active"), ("Site Update", "Success"), ("Bench", "Installing")}
			<= {(e["record_type"], e["new_status"]) for e in self.events()}
		)

	def test_unlinked_bench_failure_and_restarted_build_are_observed(self):
		bench = self.f.add("Bench", "bench-1", status="Installing")
		build = self.f.add(
			"Deploy Candidate Build", "build-1", status="Failure", deploy_candidate="candidate-1"
		)
		self.runtime.on_record(bench)
		self.runtime.on_record(build)
		self.runtime.reconcile()
		bench["status"] = "Broken"
		build["status"] = "Draft"
		self.runtime.on_record(build)
		self.runtime.reconcile()
		pairs = {(e["record_type"], e["new_status"]) for e in self.events()}
		self.assertIn(("Bench", "Broken"), pairs)
		self.assertIn(("Deploy Candidate Build", "Draft"), pairs)

	def test_queue_event_resolves_deploy_without_exporting_payload(self):
		self.f.add("Deploy", "deploy-1", candidate="candidate-1", group="group-1", team="team-1")
		self.f.add("Deploy Bench", "child-1", bench="queue-1", parent="deploy-1")
		queue = self.f.add(
			"New Bench Queue",
			"queue-1",
			status="Queued",
			group="group-1",
			payload=json.dumps({"candidate": "candidate-1", "environment_variables": "private"}),
		)
		self.runtime.on_record(queue)
		self.runtime.reconcile()
		event = self.events()[0]
		self.assertEqual(event["deploy"], "deploy-1")
		self.assertEqual(event["candidate"], "candidate-1")
		self.assertNotIn("payload", event)

	def test_failed_enqueue_does_not_break_press_work(self):
		self.f.enqueue = lambda *a, **k: (_item for _item in ()).throw(RuntimeError("private"))
		self.runtime.after_press_job(method="press.press.doctype.agent_job.agent_job.poll_pending_jobs")
		self.assertTrue(self.f.logs)
		self.assertNotIn("private", str(self.f.logs))

	def test_rc_prod_and_unknown_environment_reject_http(self):
		for environment in ("rc", "prod", None):
			self.f.conf["deployment_environment"] = environment
			with self.subTest(environment=environment), self.assertRaises(ValueError):
				self.runtime.validate_webhook(Row(endpoint="http://receiver.test/events"))
		self.runtime.validate_webhook(Row(endpoint="https://receiver.test/events"))

	def test_explicit_local_development_allows_http_only_locally(self):
		self.f.conf.update(deployment_environment="local", developer_mode=1)
		self.runtime.validate_webhook(Row(endpoint="http://127.0.0.1:9999/events"))
		with self.assertRaises(ValueError):
			self.runtime.validate_webhook(Row(endpoint="http://receiver.test/events"))

	def test_hooks_register_supported_sources_without_a_new_schedule(self):
		import ast

		tree = ast.parse((ROOT / "press_tr/hooks.py").read_text())
		settings = {}
		for node in tree.body:
			if isinstance(node, ast.Assign):
				for target in node.targets:
					if isinstance(target, ast.Name) and target.id in {
						"doc_events",
						"after_job",
						"scheduler_events",
					}:
						settings[target.id] = ast.literal_eval(node.value)
		self.assertNotIn("scheduler_events", settings)
		self.assertNotIn("Deploy", settings.get("doc_events", {}))
		for record_type, event in [
			("Agent Job", "after_insert"),
			("Agent Job", "on_update"),
			("Agent Job Callback", "after_insert"),
			("Deploy Candidate Build", "on_update"),
			("New Bench Queue", "on_update"),
			("Bench", "after_insert"),
			("Bench", "on_update"),
			("Press Webhook", "validate"),
		]:
			with self.subTest(record_type=record_type, event=event):
				self.assertIn(
					"press_tr.job_status.runtime.", settings["doc_events"].get(record_type, {}).get(event, "")
				)
		self.assertIn("press_tr.job_status.runtime.after_press_job", settings.get("after_job", []))

	def test_delivery_retries_identical_event_and_waits_for_matching_ack(self):
		self.observe_job()
		self.f.conf.update(
			press_job_status_endpoint="https://receiver.test/events",
			press_job_status_key_id="current",
			press_job_status_key="x" * 32,
		)
		calls = []

		class RequestFailure(Exception):
			pass

		requests = types.ModuleType("requests")
		requests.RequestException = RequestFailure

		def post(url, **kwargs):
			calls.append((url, copy.deepcopy(kwargs)))
			if len(calls) == 1:
				raise RequestFailure("private")
			payload = json.loads(kwargs["data"])
			return types.SimpleNamespace(
				status_code=200, json=lambda: {"message": {"accepted": True, "event_id": payload["event_id"]}}
			)

		requests.post = post
		with patch.dict(sys.modules, {"requests": requests}):
			self.runtime.dispatch()
			self.assertEqual(self.f.get_all("PTR Job Status Outbox")[0]["delivered"], 0)
			self.runtime.dispatch()
		self.assertEqual(self.f.get_all("PTR Job Status Outbox")[0]["delivered"], 1)
		self.assertEqual(calls[0][1]["data"], calls[1][1]["data"])
		self.assertFalse(calls[0][1]["allow_redirects"])
		self.assertEqual(calls[0][1]["headers"]["Content-Type"], "application/octet-stream")
		self.assertNotIn("private", str(self.f.logs))

	def test_logging_and_savepoint_failures_never_escape_hooks(self):
		def failed(*args, **kwargs):
			raise RuntimeError("private")

		self.f.log_error = self.f.enqueue = failed
		self.runtime.after_press_job(method="press.press.doctype.agent_job.agent_job.poll_pending_jobs")
		self.f.db.savepoint = self.f.db.rollback = failed
		self.runtime.on_record(self.f.add("Agent Job", "job-1", status="Running"))

	def test_two_hook_transitions_before_worker_keep_both_events(self):
		queue = self.f.add("New Bench Queue", "queue-1", status="Queued")
		self.runtime.on_record(queue)
		queue["status"] = "Started"
		self.runtime.on_record(queue)
		self.runtime.reconcile()
		self.assertEqual(
			[(e["old_status"], e["new_status"]) for e in self.events()],
			[(None, "Queued"), ("Queued", "Started")],
		)
		self.assertTrue(all(e["capture"] == "hook" for e in self.events()))

	def test_coalesced_direct_writes_disclose_reconcile_capture(self):
		bench = self.f.add("Bench", "bench-1", status="Pending")
		self.runtime.on_record(bench)
		self.runtime.reconcile()
		bench["status"] = "Installing"
		bench["status"] = "Active"
		self.runtime.reconcile()
		event = self.events()[-1]
		self.assertEqual(
			(event["old_status"], event["new_status"], event["capture"]), ("Pending", "Active", "reconcile")
		)

	def test_source_transaction_rollback_removes_outbox_and_enqueue(self):
		self.f.savepoint("transaction")
		queue = self.f.add("New Bench Queue", "queue-1", status="Queued")
		self.runtime.on_record(queue)
		self.assertEqual(len(self.events()), 1)
		self.f.db.rollback()
		self.assertEqual(self.events(), [])
		self.f.db.commit()
		self.assertEqual(self.f.queue, [])

	def test_first_queue_event_keeps_null_deploy_and_safe_candidate(self):
		queue = self.f.add(
			"New Bench Queue",
			"queue-1",
			status="Queued",
			group="group-1",
			payload=json.dumps(
				{"candidate": "candidate-1", "environment_variables": [{"key": "DEMO", "value": "private"}]}
			),
		)
		self.runtime.on_record(queue)
		first = self.events()[0]
		self.assertIsNone(first["deploy"])
		self.assertEqual(first["candidate"], "candidate-1")
		self.assertEqual(first["group"], "group-1")
		self.f.add("Deploy", "deploy-1", candidate="candidate-1", group="group-1")
		self.f.add("Deploy Bench", "child-1", bench="queue-1", parent="deploy-1")
		queue["status"] = "Started"
		self.runtime.on_record(queue)
		self.assertEqual(self.events()[-1]["deploy"], "deploy-1")
		self.assertIsNone(self.events()[0]["deploy"])
		self.assertNotIn("private", json.dumps(self.events()))

	def test_callback_reopens_terminal_job_until_committed_direct_write(self):
		job = self.f.add("Agent Job", "job-1", status="Failure")
		self.runtime.on_record(job)
		self.runtime.after_callback(Row(agent_job="job-1"))
		job["status"] = "Success"
		self.f.db.commit()
		self.runtime.reconcile()
		self.assertEqual(self.events()[-1]["new_status"], "Success")
		self.assertEqual(self.events()[-1]["capture"], "reconcile")

	def test_reconcile_locks_source_before_state_and_commits_each_observation(self):
		for name in ("bench-1", "bench-2"):
			self.runtime.on_record(self.f.add("Bench", name, status="Pending"))
		order = []
		original_get = self.f.get_doc

		def get_doc(value, name=None, **kwargs):
			if kwargs.get("for_update"):
				order.append(value)
			return original_get(value, name, **kwargs)

		self.f.get_doc = get_doc
		self.f.db.commit = lambda: order.append("commit")
		self.runtime.reconcile()
		locks = [kind for kind in order if kind != "commit"]
		self.assertEqual(locks, ["Bench", "PTR Job Status State", "Bench", "PTR Job Status State"])
		first_state = order.index("PTR Job Status State")
		self.assertEqual(order[first_state + 1], "commit")

	def test_registration_locks_each_source_before_its_tracking_write(self):
		self.f.add("Site", "site-1", status="Active")
		job = self.f.add("Agent Job", "job-1", status="Running", site="site-1")
		order = []
		get_value = self.f.db.get_value
		get_doc = self.f.get_doc

		def read(doctype, filters, fieldname="name", **kwargs):
			if kwargs.get("for_update"):
				order.append(("source", doctype))
			return get_value(doctype, filters, fieldname, **kwargs)

		def document(value, name=None, **kwargs):
			if isinstance(value, dict) and value.get("doctype") == "PTR Job Status State":
				order.append(("state", value["record_type"]))
			return get_doc(value, name, **kwargs)

		self.f.db.get_value = read
		self.f.get_doc = document
		self.runtime.after_callback(Row(agent_job=job.name))
		self.assertEqual(
			order, [("source", "Agent Job"), ("state", "Agent Job"), ("source", "Site"), ("state", "Site")]
		)
