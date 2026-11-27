"""Version Site Plan prices and notify existing subscriber teams."""

import re
from datetime import date, timedelta
from decimal import Decimal

import frappe
from babel.dates import format_date
from babel.numbers import format_decimal
from frappe import _
from press.press.doctype.communication_info.communication_info import get_communication_info

CURRENCY = "TRY"
PRICE_FIELDS = ("price_try", "price_usd", "price_inr")
PRICE_PATTERN = re.compile(r"[0-9]{1,12}(?:\.[0-9]{1,2})?")
NOTICE_TYPE = "Site Plan Price Change"


def parse_price(value: str) -> Decimal:
	if not PRICE_PATTERN.fullmatch(value):
		frappe.throw(_("Enter a price with at most two decimal places.", context="press_tr"))
	return Decimal(value)


def reject_price_edit(doc, method=None):
	before = doc.get_doc_before_save()
	if before and any((doc.get(field) or 0) != (before.get(field) or 0) for field in PRICE_FIELDS):
		frappe.throw(_("Create a new plan to change its price.", context="press_tr"))
	if before and doc.get("price_previous_plan") != before.get("price_previous_plan"):
		frappe.throw(_("You cannot change the previous plan.", context="press_tr"))

	effective_date = doc.get("price_effective_date")
	if before and str(effective_date or "") != str(before.get("price_effective_date") or ""):
		frappe.throw(_("You cannot change the price start date.", context="press_tr"))
	if effective_date and doc.enabled and frappe.utils.getdate(effective_date) > frappe.utils.getdate():
		frappe.throw(_("You can enable the plan when its price starts.", context="press_tr"))


def reject_early_subscription(doc, method=None):
	if doc.enabled and doc.plan_type == "Site Plan" and doc.plan:
		start = frappe.db.get_value("Site Plan", doc.plan, "price_effective_date")
		if start and frappe.utils.getdate(start) > frappe.utils.getdate():
			frappe.throw(_("You can assign the plan when its price starts.", context="press_tr"))


def move_subscriptions_on_activation(doc, method=None):
	previous_plan = doc.get("price_previous_plan")
	before = doc.get_doc_before_save()
	if not previous_plan or not before or before.enabled or not doc.enabled:
		return

	# This save hook moves every active subscriber, not only rows the saving user may read.
	# Each row is then reloaded under a lock and checked again before the move.
	subscriptions = frappe.get_all(
		"Subscription",
		filters={"plan_type": "Site Plan", "plan": previous_plan, "enabled": 1},
		pluck="name",
		order_by="name",
	)
	for name in subscriptions:
		subscription = frappe.get_doc("Subscription", name, for_update=True)
		if (
			subscription.enabled
			and subscription.plan_type == "Site Plan"
			and subscription.plan == previous_plan
		):
			subscription.plan = doc.name
			subscription.save()


@frappe.whitelist(methods=["GET", "POST"])
def get_panel_plans() -> list[dict]:
	from press.api import site

	plans = site.get_site_plans()
	if not plans:
		return plans
	# Press already chose these plans for the caller. This query reads only their lira price.
	prices = frappe.get_all(
		"Site Plan",
		filters={"name": ["in", [plan.name for plan in plans]]},
		fields=["name", "price_try"],
	)
	price_by_plan = {row["name"]: row["price_try"] for row in prices}
	for plan in plans:
		plan.currency = CURRENCY
		plan.price_try = price_by_plan.get(plan.name)
	return plans


class SitePlanPricing:
	def get_price_per_day(self, currency):
		if currency != CURRENCY:
			frappe.throw(_("Site plans only support Turkish lira.", context="press_tr"))
		if self.price_usd and not self.price_try:
			frappe.throw(_("Set a Turkish lira price for this paid plan.", context="press_tr"))
		return frappe.utils.rounded((self.price_try or 0) / self.period, 2)


@frappe.whitelist(methods=["POST"])
def create_price_revision(plan: str, name: str, price_try: str, price_usd: str, effective_date: str) -> str:
	frappe.only_for("System Manager")
	if not plan.strip() or not name.strip() or max(len(plan), len(name)) > 140:
		frappe.throw(_("Enter valid plan names.", context="press_tr"))

	try:
		start = date.fromisoformat(effective_date)
		if start.isoformat() != effective_date:
			raise ValueError
	except ValueError:
		frappe.throw(_("Enter a valid price start date.", context="press_tr"))

	if start < frappe.utils.getdate() + timedelta(days=30):
		frappe.throw(_("Choose a start date at least 30 days from today.", context="press_tr"))

	lira = parse_price(price_try)
	dollars = parse_price(price_usd)
	if bool(lira) != bool(dollars):
		frappe.throw(
			_(
				"Enter a USD equivalent for a paid plan. Use zero for both prices on a free plan.",
				context="press_tr",
			)
		)

	original = frappe.get_doc("Site Plan", plan)
	original.check_permission("read")
	if lira == Decimal(str(original.price_try or 0)) and dollars == Decimal(str(original.price_usd or 0)):
		frappe.throw(_("Enter a price that differs from the current price.", context="press_tr"))

	# Use the full subscriber list for this system operation. The caller receives only the new plan name.
	teams = frappe.get_all(
		"Subscription",
		filters={"plan_type": "Site Plan", "plan": original.name, "enabled": 1},
		pluck="team",
		distinct=True,
	)
	recipients_by_team = {team: get_communication_info("Email", "General", "Team", team) for team in teams}
	if any(not recipients for recipients in recipients_by_team.values()):
		frappe.throw(
			_("Add an email address for each subscriber team before changing the price.", context="press_tr")
		)

	successor = frappe.copy_doc(original)
	successor.price_try = lira
	successor.price_usd = dollars
	successor.price_effective_date = start
	successor.price_previous_plan = original.name
	successor.enabled = 0
	successor.legacy_plan = 0
	successor.insert(set_name=name)

	subject = _("Site plan price change", lang="tr", context="press_tr")
	amount = format_decimal(lira, format="#,##0.00", locale="tr")
	start_date = format_date(start, format="d MMMM y EEEE", locale="tr")
	message = _("The new plan price is {0} TRY from {1}.", lang="tr", context="press_tr").format(
		amount, start_date
	)
	for team, recipients in recipients_by_team.items():
		notify_team(team, original.name, successor.name, subject, message, recipients)
	return successor.name


def notify_team(team, plan, successor, subject, message, recipients):
	notice = frappe.get_doc(
		{
			"doctype": "Press Notification",
			"type": NOTICE_TYPE,
			"team": team,
			"document_type": "Site Plan",
			"document_name": plan,
			"reference_doctype": "Site Plan",
			"reference_name": successor,
			"class": "Info",
			"title": subject,
			"message": message,
		}
	).insert()
	frappe.sendmail(
		recipients=recipients,
		subject=subject,
		message=message,
		reference_doctype=notice.doctype,
		reference_name=notice.name,
	)
