"""G-149: first-party real user monitoring (RUM). The collection point keeps no personal data.

The browser sends web-vitals values with a route template, such as `/panel/leave-application/:name`.
A beacon with any other field is refused. The server never adds the user, the IP address or
the browser name. Each beacon becomes one JSON line in the `platform_core.rum` log, which
DevOps forwards to Grafana for p75 and p95 views. No third party receives the data.
"""

import json
import logging
import math
import re

import frappe
from frappe import _

# Upper bounds stop broken or hostile values. Durations are milliseconds; CLS has no unit.
METRICS = {"LCP": 120_000, "INP": 120_000, "FCP": 120_000, "TTFB": 120_000, "CLS": 100}
NAVIGATION_TYPES = {"navigate", "reload", "back-forward", "back-forward-cache", "prerender", "restore"}
FIELDS = {"route", "metrics", "sample_rate", "navigation_type"}
ROUTE_MAX = 200
# A route template has lowercase words or `:parameter` segments. Digits, dots, `@`, `?` and `#` are
# refused, so a record name, an e-mail address or a query cannot pass as a route.
ROUTE = re.compile(r"/(?:(?:[a-z][a-z_-]*|:[a-z][a-z_]*)(?:/(?:[a-z][a-z_-]*|:[a-z][a-z_]*))*)?")
LOGGER = "platform_core.rum"


def refuse(message: str):
	frappe.throw(_(message), frappe.ValidationError)


def number(value) -> bool:
	return type(value) in (int, float) and math.isfinite(value)


def clean_beacon(beacon) -> dict:
	"""Return the beacon with checked values. Raise ValidationError for anything else."""
	if not isinstance(beacon, dict):
		refuse("The RUM beacon must be a JSON object.")
	if set(beacon) - FIELDS:
		refuse("The RUM beacon has a field that is not allowed.")
	route = beacon.get("route")
	if not isinstance(route, str) or len(route) > ROUTE_MAX or not ROUTE.fullmatch(route):
		refuse("The route must be a route template, such as /panel/leave-application/:name.")
	metrics = beacon.get("metrics")
	if not isinstance(metrics, dict) or not metrics or set(metrics) - set(METRICS):
		refuse("Send at least one of LCP, INP, CLS, FCP and TTFB.")
	for name, value in metrics.items():
		if not number(value) or not 0 <= value <= METRICS[name]:
			refuse("A metric value is out of range.")
	sample_rate = beacon.get("sample_rate", 1.0)
	if not number(sample_rate) or not 0 < sample_rate <= 1:
		refuse("The sample rate must be above 0 and at most 1.")
	record = {"route": route, "metrics": dict(metrics), "sample_rate": float(sample_rate)}
	if "navigation_type" in beacon:
		if beacon["navigation_type"] not in NAVIGATION_TYPES:
			refuse("The navigation type is not known.")
		record["navigation_type"] = beacon["navigation_type"]
	return record


def store(record: dict) -> None:
	"""Write one JSON line. The line has only the cleaned beacon fields."""
	logger = frappe.logger(LOGGER, allow_site=True)
	# Frappe logs only errors outside the dev server. The RUM log is data, so it keeps INFO lines.
	logger.setLevel(logging.INFO)
	logger.info(json.dumps(record, sort_keys=True))
