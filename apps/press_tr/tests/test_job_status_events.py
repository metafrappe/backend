"""AJA-192 and AJA-203 status transition acceptance examples."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from press_tr.job_status.events import build_event, is_active


class StatusTransitionTests(unittest.TestCase):
	def event(self, record_type="Agent Job", old="Running", new="Success", **extra):
		record = dict(
			doctype=record_type,
			name="record-1",
			status=new,
			team="team-1",
			site="site.test",
			data="private",
			output="private",
			traceback="private",
			payload="private",
			modified="unchanged",
			**extra,
		)
		return build_event(
			record, old, event_id="event-1", occurred_at="2026-11-24T00:00:00Z", capture="reconcile"
		)

	def test_polled_job_records_one_status_transition(self):
		event = self.event()
		self.assertEqual((event["old_status"], event["new_status"]), ("Running", "Success"))
		self.assertIsNone(self.event(old="Success"))

	def test_fail_old_jobs_does_not_require_modified_change(self):
		event = self.event(old="Pending", new="Failure")
		self.assertEqual(event["new_status"], "Failure")
		self.assertNotIn("modified", event)

	def test_site_and_site_update_direct_writes_are_observable(self):
		for record_type in ("Site", "Site Update"):
			with self.subTest(record_type=record_type):
				event = self.event(record_type=record_type)
				self.assertEqual(event["record_type"], record_type)
				self.assertEqual(event["new_status"], "Success")

	def test_deploy_does_not_invent_a_status_event(self):
		self.assertIsNone(self.event(record_type="Deploy"))

	def test_build_uses_actual_status_and_relationships(self):
		event = self.event(record_type="Deploy Candidate Build", group="group-1", candidate="candidate-1")
		self.assertEqual(event["event_type"], "press.deploy_candidate_build.status")
		self.assertEqual(event["group"], "group-1")
		self.assertEqual(event["candidate"], "candidate-1")
		self.assertIsNone(event["deploy"])

	def test_each_queue_starts_at_queued_with_deploy_link(self):
		event = self.event(record_type="New Bench Queue", old=None, new="Queued", deploy="deploy-1")
		self.assertEqual(event["event_type"], "press.new_bench_queue.status")
		self.assertEqual((event["old_status"], event["new_status"]), (None, "Queued"))
		self.assertEqual(event["deploy"], "deploy-1")

	def test_queue_success_starts_bench_tracking(self):
		queue = self.event(record_type="New Bench Queue", old="Queued", new="Started")
		bench = self.event(record_type="Bench", old=None, new="Pending")
		self.assertEqual(queue["new_status"], "Started")
		self.assertEqual((bench["old_status"], bench["new_status"]), (None, "Pending"))

	def test_queue_failure_uses_actual_terminal_status(self):
		self.assertEqual(
			self.event(record_type="New Bench Queue", old="Queued", new="Failure")["new_status"], "Failure"
		)

	def test_bench_set_value_transitions_remain_distinct(self):
		old = None
		for new in ("Pending", "Installing", "Active"):
			event = self.event(record_type="Bench", old=old, new=new)
			self.assertEqual((event["old_status"], event["new_status"]), (old, new))
			old = new
		self.assertIsNone(self.event(record_type="Bench", old="Active", new="Active"))

	def test_release_pipeline_failure_is_not_filtered_by_modified(self):
		self.assertEqual(
			self.event(record_type="Bench", old="Installing", new="Broken")["new_status"], "Broken"
		)

	def test_execution_data_is_never_copied(self):
		for record_type in (
			"Agent Job",
			"Site",
			"Site Update",
			"Deploy Candidate Build",
			"New Bench Queue",
			"Bench",
		):
			with self.subTest(record_type=record_type):
				event = self.event(record_type=record_type)
				self.assertFalse({"data", "output", "traceback", "payload", "modified"} & event.keys())

	def test_terminal_records_stop_and_restarted_builds_resume(self):
		for record_type, status in (
			("Agent Job", "Success"),
			("Agent Job", "Failure"),
			("Agent Job", "Undelivered"),
			("Deploy Candidate Build", "Failure"),
			("New Bench Queue", "Started"),
			("Bench", "Active"),
			("Bench", "Broken"),
			("Bench", "Archived"),
		):
			with self.subTest(record_type=record_type, status=status):
				self.assertFalse(is_active(record_type, status))
		self.assertTrue(is_active("Deploy Candidate Build", "Draft"))
		self.assertTrue(is_active("Bench", "Installing"))
