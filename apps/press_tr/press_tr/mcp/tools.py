"""Commercial tools of the press_tr MCP server (G-27).

A tool that changes billing or a site takes `confirm`. Without `confirm=True` it changes nothing
and returns only a preview. Every call goes through `history.recorded`.
"""

import frappe
from frappe import _

from press_tr.mcp import mcp
from press_tr.mcp.history import recorded

DEFAULT_LIMIT = 20
MAX_LIMIT = 100


def _limit(value) -> int:
	try:
		return max(1, min(int(value or DEFAULT_LIMIT), MAX_LIMIT))
	except TypeError, ValueError:
		return DEFAULT_LIMIT


def _require(doctype: str, name: str) -> None:
	if not name or not frappe.db.exists(doctype, name):
		frappe.throw(
			_("{0} {1} was not found.", context="press_tr").format(doctype, name),
			frappe.DoesNotExistError,
		)


def _check_app_plan(app: str, plan: str) -> None:
	_require("Marketplace App Plan", plan)
	if frappe.get_doc("Marketplace App Plan", plan).app != app:
		frappe.throw(_("The plan does not belong to this app.", context="press_tr"))


def _preview(action: str, **details) -> dict:
	return {
		"action": action,
		**details,
		"preview": True,
		"requires_confirm": True,
		"next_step": "Call again with confirm=true to run this action.",
	}


@mcp.tool()
@recorded
def list_marketplace_apps(limit: int = DEFAULT_LIMIT) -> list:
	"""List published Marketplace apps. Read only."""
	return frappe.get_all(
		"Marketplace App",
		filters={"status": "Published"},
		fields=["name", "title", "description"],
		order_by="title asc",
		limit_page_length=_limit(limit),
	)


@mcp.tool()
@recorded
def get_app_plans(app: str) -> list:
	"""List the enabled plans of one Marketplace app. Read only."""
	return frappe.get_all(
		"Marketplace App Plan",
		filters={"app": app, "enabled": 1},
		fields=["name", "title", "interval", "price_inr", "price_usd"],
		order_by="price_usd asc",
	)


@mcp.tool()
@recorded
def install_app(site: str, app: str, plan: str | None = None, confirm: bool = False) -> dict:
	"""Install a Marketplace app on a site, with an optional paid plan.

	Without confirm=true this returns a preview and changes nothing.
	"""
	_require("Site", site)
	_require("Marketplace App", app)
	if plan:
		_check_app_plan(app, plan)
	if confirm is not True:
		return _preview("install_app", site=site, app=app, plan=plan)
	frappe.get_doc("Site", site).install_app(app, plan)
	return {"action": "install_app", "site": site, "app": app, "plan": plan, "status": "triggered"}


@mcp.tool()
@recorded
def change_app_plan(subscription: str, new_plan: str, confirm: bool = False) -> dict:
	"""Move a Marketplace app subscription to another plan of the same app.

	Without confirm=true this returns a preview and changes nothing.
	"""
	_require("Subscription", subscription)
	doc = frappe.get_doc("Subscription", subscription)
	if doc.document_type != "Marketplace App":
		frappe.throw(_("The subscription is not for a Marketplace app.", context="press_tr"))
	_check_app_plan(doc.document_name, new_plan)
	if confirm is not True:
		return _preview(
			"change_app_plan", subscription=subscription, current_plan=doc.plan, new_plan=new_plan
		)
	doc.enabled = 1
	doc.plan = new_plan
	doc.save(ignore_permissions=True)
	return {"action": "change_app_plan", "subscription": subscription, "plan": new_plan, "status": "done"}


@mcp.tool()
@recorded
def change_site_plan(site: str, plan: str, confirm: bool = False) -> dict:
	"""Move a site to another site plan.

	Without confirm=true this returns a preview and changes nothing.
	"""
	_require("Site", site)
	_require("Site Plan", plan)
	doc = frappe.get_doc("Site", site)
	if confirm is not True:
		return _preview("change_site_plan", site=site, current_plan=doc.plan, new_plan=plan)
	doc.set_plan(plan)
	return {"action": "change_site_plan", "site": site, "plan": plan, "status": "done"}


@mcp.tool()
@recorded
def get_invoices(team: str, limit: int = DEFAULT_LIMIT) -> list:
	"""List the latest invoices of a team. Read only."""
	return frappe.get_all(
		"Invoice",
		filters={"team": team},
		fields=[
			"name",
			"status",
			"type",
			"currency",
			"total",
			"amount_due",
			"period_start",
			"period_end",
			"due_date",
		],
		order_by="creation desc",
		limit_page_length=_limit(limit),
	)


@mcp.tool()
@recorded
def get_upcoming_invoice(team: str) -> dict | None:
	"""Show the open invoice of a team for the current period. Read only."""
	_require("Team", team)
	invoice = frappe.get_doc("Team", team).get_upcoming_invoice()
	if not invoice:
		return None
	return {
		"name": invoice.name,
		"currency": invoice.currency,
		"total": invoice.total,
		"period_start": str(invoice.period_start),
		"period_end": str(invoice.period_end),
	}


@mcp.tool()
@recorded
def get_agent_job_status(job: str) -> dict:
	"""Show the status of one Agent Job. Read only."""
	row = frappe.db.get_value(
		"Agent Job",
		job,
		["name", "status", "job_type", "site", "bench", "server", "start", "end"],
		as_dict=True,
	)
	if not row:
		frappe.throw(
			_("{0} {1} was not found.", context="press_tr").format("Agent Job", job),
			frappe.DoesNotExistError,
		)
	return row
