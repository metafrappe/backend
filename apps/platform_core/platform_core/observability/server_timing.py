"""G-149: the `Server-Timing` header on every tenant response.

The `before_request` hook starts the clock. The `after_request` hook adds `app;dur=<ms>`.
The header carries only the metric name and the duration. It has no description text,
so it cannot leak a route, a query or a name. Grafana and the load trial read the same value.
"""

from time import perf_counter

import frappe

HEADER = "Server-Timing"
START_KEY = "plt_request_started"


def format_server_timing(metrics: dict[str, float]) -> str:
	"""Write the metrics as `name;dur=<ms>` entries with one decimal."""
	return ", ".join(f"{name};dur={round(duration, 1):g}" for name, duration in metrics.items())


def start_request_timer(clock=perf_counter) -> None:
	"""Remember when the request reached the app. Frappe runs this first in `before_request`."""
	setattr(frappe.local, START_KEY, clock())


def add_server_timing(response, request=None, clock=perf_counter) -> None:
	"""Add the app duration to the response. A request without a start time gets no header."""
	started = getattr(frappe.local, START_KEY, None)
	if response is None or started is None:
		return
	response.headers.add(HEADER, format_server_timing({"app": (clock() - started) * 1000}))
