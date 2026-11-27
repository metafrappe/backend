"""Calendar days and instants as separate types (AJA-1769, `docs/contracts.md`).

- A calendar day is a date without a time. It never shifts with the time zone.
- A closing instant is one point in time. It is stored in UTC and shown in the reader's time zone.
- A local wall time inside the repeated hour of a daylight saving change needs an explicit `fold`.
  A local wall time inside the skipped hour is rejected.

The module uses only the standard library, so the API layer and notifications share it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class AmbiguousLocalTimeError(ValueError):
	"""The local wall time happens twice in this time zone. The caller must pass `fold`."""


class NonexistentLocalTimeError(ValueError):
	"""The local wall time does not happen in this time zone. The clocks skip it."""


def _zone(name: str) -> ZoneInfo:
	try:
		return ZoneInfo(name)
	except (ZoneInfoNotFoundError, ValueError, TypeError) as error:
		raise ValueError(f"Unknown time zone: {name!r}") from error


@dataclass(frozen=True)
class CalendarDay:
	"""A date without a time and without a time zone."""

	value: date

	def __post_init__(self):
		if type(self.value) is not date:
			raise TypeError("CalendarDay takes a date, not a datetime.")

	@classmethod
	def parse(cls, raw: str) -> CalendarDay:
		if not isinstance(raw, str) or len(raw) != 10:
			raise ValueError(f"Calendar day must be YYYY-MM-DD: {raw!r}")
		return cls(date.fromisoformat(raw))

	def in_time_zone(self, time_zone: str) -> date:
		"""The same day in every time zone. The zone is checked but not applied."""
		_zone(time_zone)
		return self.value

	def to_api(self) -> str:
		return self.value.isoformat()


def closing_instant(local: datetime, time_zone: str, fold: int | None = None) -> datetime:
	"""Turn a closing time into one UTC instant.

	An aware `local` keeps its instant. A naive `local` is read as wall time in `time_zone`.
	"""
	zone = _zone(time_zone)
	if local.tzinfo is not None:
		return local.astimezone(UTC)

	early = local.replace(tzinfo=zone, fold=0)
	late = local.replace(tzinfo=zone, fold=1)
	if early.utcoffset() != late.utcoffset():
		round_trip = early.astimezone(UTC).astimezone(zone).replace(tzinfo=None)
		if round_trip != local:
			raise NonexistentLocalTimeError(f"{local.isoformat()} does not exist in {time_zone}.")
		if fold not in (0, 1):
			raise AmbiguousLocalTimeError(
				f"{local.isoformat()} happens twice in {time_zone}. Pass fold=0 or fold=1."
			)
		chosen = late if fold == 1 else early
	else:
		chosen = early
	return chosen.astimezone(UTC)


def parse_instant(raw: str) -> datetime:
	"""Read an ISO 8601 instant. The offset is required."""
	moment = datetime.fromisoformat(raw)
	if moment.tzinfo is None:
		raise ValueError(f"Instant needs a time zone offset: {raw!r}")
	return moment.astimezone(UTC)


def _require_utc(instant: datetime) -> datetime:
	if instant.tzinfo is None:
		raise ValueError("Stored instant must be aware.")
	return instant.astimezone(UTC)


def closing_payload(instant: datetime, time_zone: str) -> dict[str, str]:
	"""The API fields for one closing instant."""
	stored = _require_utc(instant)
	return {
		"closes_at": stored.isoformat(),
		"time_zone": time_zone,
		"closes_at_local": stored.astimezone(_zone(time_zone)).isoformat(),
	}


def closing_notice(instant: datetime, time_zone: str) -> str:
	"""Notification text. It carries the same local value and offset as the API response."""
	payload = closing_payload(instant, time_zone)
	return f"Closes at {payload['closes_at_local']} ({payload['time_zone']})."
