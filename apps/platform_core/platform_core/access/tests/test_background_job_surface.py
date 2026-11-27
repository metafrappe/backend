"""Background jobs: a job runs as the user who queued it, so the rule follows it (G-121).

Frappe stores the requesting user with the job (`frappe/utils/background_jobs.py:179`). The
worker sets that user before it calls the method (`background_jobs.py:251`). The test site has
no worker. `run_as_worker` does the same two steps in this process: it sets the stored user and
calls `execute_job` without starting a new site connection.
"""

import json

import frappe
from frappe.utils.background_jobs import execute_job, get_queue

from platform_core.access.tests.base import (
	DOCTYPE,
	EMPLOYEE_1,
	EXPECTED_VISIBLE,
	MANAGER_1,
	AccessRuleTestCase,
)

ASYNC_PDF = "/api/method/frappe.utils.print_format.download_multi_pdf_async"
ASYNC_PDF_JOB = "frappe.utils.print_format._download_multi_pdf"


def method_name(method) -> str:
	return method if isinstance(method, str) else f"{method.__module__}.{method.__qualname__}"


def run_as_worker(job_kwargs: dict):
	"""Runs a queued job the way the worker does: as the user stored with the job."""
	frappe.set_user(job_kwargs["user"])
	try:
		return execute_job(**{**job_kwargs, "is_async": False})
	finally:
		frappe.set_user("Administrator")


class TestBackgroundJobSurface(AccessRuleTestCase):
	def queued_pdf_jobs(self, user: str) -> list:
		jobs = []
		for queue in ("short", "long"):
			for job in get_queue(queue).jobs:
				if job.kwargs.get("user") == user and method_name(job.kwargs.get("method")) == ASYNC_PDF_JOB:
					jobs.append(job)
		return jobs

	def drop_pdf_jobs(self, user: str) -> None:
		for job in self.queued_pdf_jobs(user):
			job.delete()

	def setUp(self):
		super().setUp()
		self.drop_pdf_jobs(EMPLOYEE_1)
		frappe.cache.delete_value(frappe.cache.make_key(f"rl:multi_pdf_async:{EMPLOYEE_1}"))

	def tearDown(self):
		self.drop_pdf_jobs(EMPLOYEE_1)
		super().tearDown()

	def test_queued_pdf_job_of_a_hidden_record_is_refused_in_the_worker(self):
		client = self.login(EMPLOYEE_1)
		other = self.records[MANAGER_1]

		response = self.send(
			client, "POST", ASYNC_PDF, body={"doctype": DOCTYPE, "name": json.dumps([other])}
		)

		self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
		task_id = response.json["message"]["task_id"]
		jobs = self.queued_pdf_jobs(EMPLOYEE_1)
		self.assertEqual(len(jobs), 1)
		self.assertEqual(jobs[0].kwargs["user"], EMPLOYEE_1)
		with self.assertRaises(frappe.PermissionError):
			run_as_worker(jobs[0].kwargs)
		self.assertFalse(frappe.db.exists("File", {"file_name": ("like", f"%{task_id}.pdf")}))

	def test_job_reads_only_the_records_of_its_user(self):
		job = {
			"site": frappe.local.site,
			"method": "frappe.client.get_list",
			"event": None,
			"job_name": "g121-background-read",
			"kwargs": {"doctype": DOCTYPE, "fields": ["name"], "limit_page_length": 0},
			"user": EMPLOYEE_1,
		}

		rows = run_as_worker(job)

		self.assertEqual({row["name"] for row in rows}, self.names_of(EXPECTED_VISIBLE[EMPLOYEE_1]))

	def test_job_cannot_read_a_hidden_record(self):
		job = {
			"site": frappe.local.site,
			"method": "frappe.client.get",
			"event": None,
			"job_name": "g121-background-get",
			"kwargs": {"doctype": DOCTYPE, "name": self.records[MANAGER_1]},
			"user": EMPLOYEE_1,
		}

		with self.assertRaises(frappe.PermissionError):
			run_as_worker(job)
