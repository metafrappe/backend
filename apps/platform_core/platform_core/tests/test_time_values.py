"""Calendar days and instants are separate types (AJA-1769, AJA-1732, `docs/contracts.md`).

A calendar day never moves with the time zone. A closing instant is stored once, in UTC, and every
reader (API response, notification text) shows that same instant in its own time zone.
The module has no Frappe dependency, so these tests run with plain `unittest`.
"""

import unittest
from datetime import UTC, date, datetime

from platform_core.time_values import (
	AmbiguousLocalTimeError,
	CalendarDay,
	NonexistentLocalTimeError,
	closing_instant,
	closing_notice,
	closing_payload,
	parse_instant,
)

LONDON = "Europe/London"
ISTANBUL = "Europe/Istanbul"
NEW_YORK = "America/New_York"


class CalendarDayTests(unittest.TestCase):
	def test_calendar_day_does_not_shift_with_time_zone(self):
		day = CalendarDay.parse("2026-03-29")
		for zone in (LONDON, ISTANBUL, NEW_YORK, "Pacific/Kiritimati", "Pacific/Pago_Pago"):
			with self.subTest(zone=zone):
				self.assertEqual(day.in_time_zone(zone).isoformat(), "2026-03-29")
		self.assertEqual(day.to_api(), "2026-03-29")

	def test_calendar_day_rejects_a_value_with_time(self):
		for raw in ("2026-03-29T00:00:00", "2026-03-29T00:00:00+03:00", "29.03.2026", ""):
			with self.subTest(raw=raw), self.assertRaises(ValueError):
				CalendarDay.parse(raw)

	def test_calendar_day_is_not_a_datetime(self):
		self.assertEqual(CalendarDay.parse("2026-03-29").value, date(2026, 3, 29))
		with self.assertRaises(TypeError):
			CalendarDay(datetime(2026, 3, 29, 12, 0))


class ClosingInstantTests(unittest.TestCase):
	def test_closing_instant_is_stored_in_utc_with_offset(self):
		stored = closing_instant(datetime(2026, 7, 1, 18, 0), ISTANBUL)
		self.assertEqual(stored.utcoffset().total_seconds(), 0)
		self.assertEqual(stored.isoformat(), "2026-07-01T15:00:00+00:00")
		self.assertEqual(
			closing_instant(datetime(2026, 7, 1, 18, 0), LONDON).isoformat(), "2026-07-01T17:00:00+00:00"
		)

	def test_aware_input_keeps_its_instant(self):
		aware = datetime(2026, 7, 1, 18, 0, tzinfo=UTC)
		self.assertEqual(closing_instant(aware, ISTANBUL), aware)

	def test_unknown_time_zone_is_rejected(self):
		with self.assertRaises(ValueError):
			closing_instant(datetime(2026, 7, 1, 18, 0), "Mars/Olympus")

	def test_parse_instant_requires_an_offset(self):
		self.assertEqual(parse_instant("2026-03-29T03:30:00+03:00").isoformat(), "2026-03-29T00:30:00+00:00")
		with self.assertRaises(ValueError):
			parse_instant("2026-03-29T03:30:00")


class DaylightSavingTests(unittest.TestCase):
	def test_api_and_notification_show_the_same_instant_on_transition_night(self):
		# London moves its clocks forward on 29 March 2026 at 01:00 UTC.
		stored = closing_instant(datetime(2026, 3, 29, 2, 30), LONDON)
		self.assertEqual(stored.isoformat(), "2026-03-29T01:30:00+00:00")
		for zone in (LONDON, ISTANBUL):
			with self.subTest(zone=zone):
				payload = closing_payload(stored, zone)
				notice = closing_notice(stored, zone)
				self.assertEqual(payload["closes_at"], "2026-03-29T01:30:00+00:00")
				self.assertEqual(payload["time_zone"], zone)
				self.assertEqual(parse_instant(payload["closes_at_local"]), stored)
				self.assertIn(payload["closes_at_local"], notice)
		self.assertEqual(closing_payload(stored, LONDON)["closes_at_local"], "2026-03-29T02:30:00+01:00")
		self.assertEqual(closing_payload(stored, ISTANBUL)["closes_at_local"], "2026-03-29T04:30:00+03:00")

	def test_repeated_hour_needs_a_choice_and_stores_one_instant(self):
		# London moves its clocks back on 25 October 2026. 01:30 happens twice.
		repeated = datetime(2026, 10, 25, 1, 30)
		with self.assertRaises(AmbiguousLocalTimeError):
			closing_instant(repeated, LONDON)
		first = closing_instant(repeated, LONDON, fold=0)
		second = closing_instant(repeated, LONDON, fold=1)
		self.assertEqual(first.isoformat(), "2026-10-25T00:30:00+00:00")
		self.assertEqual(second.isoformat(), "2026-10-25T01:30:00+00:00")
		self.assertEqual(closing_payload(first, LONDON)["closes_at_local"], "2026-10-25T01:30:00+01:00")
		self.assertEqual(closing_payload(second, LONDON)["closes_at_local"], "2026-10-25T01:30:00+00:00")
		self.assertEqual(parse_instant(closing_payload(first, LONDON)["closes_at_local"]), first)
		self.assertEqual(parse_instant(closing_payload(second, LONDON)["closes_at_local"]), second)

	def test_skipped_hour_is_rejected(self):
		with self.assertRaises(NonexistentLocalTimeError):
			closing_instant(datetime(2026, 3, 29, 1, 30), LONDON)

	def test_fold_is_ignored_when_the_hour_is_not_repeated(self):
		self.assertEqual(
			closing_instant(datetime(2026, 7, 1, 18, 0), LONDON, fold=1).isoformat(),
			"2026-07-01T17:00:00+00:00",
		)


if __name__ == "__main__":
	unittest.main()
