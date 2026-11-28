"""G-139: per-user tour progress rules. No Frappe site is needed.

The expected results come from requirement G-139 in `src/data/requirements.json`:
progress is stored by user, tour and version; a new tour version shows only the new
steps; the user can skip, snooze, restart and resume a tour.
"""

import unittest

from platform_core.shell.tour_rules import (
	MAX_SEEN_STEPS,
	TourProgressError,
	merge_progress,
	normalize_progress,
	progress_name,
)


def payload(**changes):
	value = {
		"tour_id": "leave-application",
		"version": 1,
		"status": "active",
		"current_step": "leave-type",
		"seen_steps": ["intro"],
	}
	value.update(changes)
	return value


class TestNormalizeProgress(unittest.TestCase):
	def test_accepts_a_valid_payload(self):
		self.assertEqual(
			normalize_progress(payload()),
			{
				"tour_id": "leave-application",
				"version": 1,
				"status": "active",
				"current_step": "leave-type",
				"seen_steps": ["intro"],
			},
		)

	def test_every_documented_status_is_accepted(self):
		for status in ("active", "snoozed", "skipped", "completed"):
			self.assertEqual(normalize_progress(payload(status=status))["status"], status)

	def test_empty_current_step_becomes_none(self):
		self.assertIsNone(normalize_progress(payload(current_step=""))["current_step"])
		self.assertIsNone(normalize_progress(payload(current_step=None))["current_step"])

	def test_seen_steps_keep_first_order_without_duplicates(self):
		value = normalize_progress(payload(seen_steps=["a", "b", "a", "c"]))
		self.assertEqual(value["seen_steps"], ["a", "b", "c"])

	def test_version_may_arrive_as_text_from_a_query(self):
		self.assertEqual(normalize_progress(payload(version="3"))["version"], 3)

	def test_rejects_bad_values(self):
		bad = [
			payload(tour_id=""),
			payload(tour_id="Leave Application"),
			payload(tour_id="x" * 81),
			payload(tour_id="../etc"),
			payload(version=0),
			payload(version=-1),
			payload(version=100_001),
			payload(version="one"),
			payload(version=True),
			payload(version=1.5),
			payload(status="closed"),
			payload(current_step="Bad Step"),
			payload(seen_steps="intro"),
			payload(seen_steps=[1]),
			payload(seen_steps=["Bad Step"]),
			payload(seen_steps=[f"s{n}" for n in range(MAX_SEEN_STEPS + 1)]),
		]
		for value in bad:
			with self.subTest(value=value), self.assertRaises(TourProgressError):
				normalize_progress(value)

	def test_rejects_unknown_and_missing_keys(self):
		with self.assertRaises(TourProgressError):
			normalize_progress(payload(user="someone@example.test"))
		value = payload()
		del value["status"]
		with self.assertRaises(TourProgressError):
			normalize_progress(value)


class TestMergeProgress(unittest.TestCase):
	def test_first_save_is_stored_as_given(self):
		incoming = normalize_progress(payload())
		self.assertEqual(merge_progress(None, incoming), incoming)

	def test_seen_steps_are_never_forgotten(self):
		stored = normalize_progress(payload(seen_steps=["intro", "leave-type"]))
		incoming = normalize_progress(payload(seen_steps=["intro", "dates"]))
		self.assertEqual(merge_progress(stored, incoming)["seen_steps"], ["intro", "leave-type", "dates"])

	def test_restart_clears_seen_steps(self):
		stored = normalize_progress(payload(status="completed", seen_steps=["intro", "leave-type"]))
		incoming = normalize_progress(payload(status="active", current_step="intro", seen_steps=[]))
		merged = merge_progress(stored, incoming, restart=True)
		self.assertEqual(merged["seen_steps"], [])
		self.assertEqual(merged["status"], "active")
		self.assertEqual(merged["current_step"], "intro")

	def test_an_older_version_does_not_lower_the_stored_version(self):
		stored = normalize_progress(payload(version=3, status="completed", seen_steps=["intro", "new"]))
		incoming = normalize_progress(payload(version=2, status="active", seen_steps=["intro"]))
		merged = merge_progress(stored, incoming)
		self.assertEqual(merged["version"], 3)
		self.assertEqual(merged["status"], "completed")
		self.assertEqual(merged["seen_steps"], ["intro", "new"])

	def test_a_newer_version_is_stored(self):
		stored = normalize_progress(payload(version=1, status="completed"))
		incoming = normalize_progress(payload(version=2, status="active", current_step="new"))
		merged = merge_progress(stored, incoming)
		self.assertEqual(merged["version"], 2)
		self.assertEqual(merged["status"], "active")
		self.assertEqual(merged["current_step"], "new")

	def test_merged_seen_steps_stay_within_the_limit(self):
		stored = normalize_progress(payload(seen_steps=[f"a{n}" for n in range(MAX_SEEN_STEPS)]))
		incoming = normalize_progress(payload(seen_steps=["late"]))
		self.assertEqual(len(merge_progress(stored, incoming)["seen_steps"]), MAX_SEEN_STEPS)


class TestProgressName(unittest.TestCase):
	def test_name_depends_on_user_and_tour(self):
		first = progress_name("a@example.test", "leave-application")
		self.assertEqual(first, progress_name("a@example.test", "leave-application"))
		self.assertNotEqual(first, progress_name("b@example.test", "leave-application"))
		self.assertNotEqual(first, progress_name("a@example.test", "expense-claim"))

	def test_name_hides_the_email_and_fits_a_frappe_name(self):
		name = progress_name("a@example.test", "leave-application")
		self.assertNotIn("example", name)
		self.assertLessEqual(len(name), 140)


if __name__ == "__main__":
	unittest.main()
