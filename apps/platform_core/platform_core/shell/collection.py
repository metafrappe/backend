"""Read grouped summaries from the same permitted rows as the native document list."""

import json
import math
import re
from typing import Annotated, Literal

import frappe
from frappe.model import get_permitted_fields, numeric_fieldtypes
from frappe.model.document import get_controller
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from pydantic import ValidationError as QueryValidationError
from pypika import functions
from pypika.terms import AnalyticFunction

from platform_core.shell.request_policy import FRAMEWORK_PARAMETERS

FIELD_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]*$"
FIELD_NAME = Annotated[str, StringConstraints(pattern=FIELD_PATTERN, max_length=140)]
FILTER_OPERATORS = {"=", "!=", ">", ">=", "<", "<=", "like", "not like", "in", "not in", "between", "is"}
MAX_GROUPS = 100
# O-73: one list page holds at most this many rows, whatever the request asks for.
MAX_PAGE_LENGTH = 20
ORDER_PATTERN = r"^([A-Za-z_][A-Za-z0-9_]*)(?: (asc|desc))?$"
CHILD_SCOPE = ("parent", "parenttype", "parentfield")
TABLE_FIELDTYPES = {"Table", "Table MultiSelect"}


class InvalidSummaryQuery(frappe.ValidationError):
	http_status_code = 400


class InvalidListQuery(frappe.ValidationError):
	pass


class SummaryQuery(BaseModel):
	model_config = ConfigDict(extra="forbid")

	doctype: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=140)]
	group_by: FIELD_NAME
	aggregate: Literal["sum", "avg"] | None = None
	aggregate_field: FIELD_NAME | None = None
	filters: Annotated[str, StringConstraints(max_length=8192)] | None = None
	limit: int = Field(default=MAX_GROUPS, ge=1, le=MAX_GROUPS)


def invalid_query() -> None:
	frappe.throw(
		frappe._("The collection summary parameters are invalid.", context="shell.collection"),
		InvalidSummaryQuery,
	)


class ListQuery(BaseModel):
	model_config = ConfigDict(extra="forbid")

	doctype: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=140)]
	parent: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=140)] | None = (
		None
	)
	fields: Annotated[str, StringConstraints(max_length=8192)] | None = None
	filters: Annotated[str, StringConstraints(max_length=8192)] | None = None
	order_by: Annotated[str, StringConstraints(max_length=1000)] | None = None
	limit_start: int = Field(default=0, ge=0)
	limit_page_length: int = Field(default=MAX_PAGE_LENGTH, ge=1)


def invalid_list() -> None:
	frappe.throw(
		frappe._("The collection list parameters are invalid.", context="shell.collection"),
		InvalidListQuery,
	)


def read_query() -> SummaryQuery:
	request_params = {
		key: argument for key, argument in frappe.form_dict.items() if key not in FRAMEWORK_PARAMETERS
	}
	try:
		query = SummaryQuery.model_validate(request_params)
	except QueryValidationError:
		invalid_query()
	if bool(query.aggregate) != bool(query.aggregate_field):
		invalid_query()
	return query


def filter_rows(raw_filters: str | None, doctype: str, invalid=invalid_query) -> list[tuple]:
	if raw_filters is None:
		return []
	try:
		filters = json.loads(raw_filters)
	except ValueError:
		invalid()
	if isinstance(filters, dict):
		filters = [
			[fieldname, *operand] if isinstance(operand, list) else [fieldname, "=", operand]
			for fieldname, operand in filters.items()
		]
	if not isinstance(filters, list) or len(filters) > 100:
		invalid()

	conditions = []
	for condition in filters:
		if not isinstance(condition, list) or len(condition) not in (3, 4):
			invalid()
		if len(condition) == 4 and condition[0] != doctype:
			invalid()
		fieldname, operator, operand = condition[-3:]
		if not isinstance(operator, str) or operator.lower() not in FILTER_OPERATORS:
			invalid()
		operator = operator.lower()
		operands = operand if isinstance(operand, list) else [operand]
		needs_list = operator in {"in", "not in", "between"}
		if (
			needs_list != isinstance(operand, list)
			or len(operands) > 100
			or (needs_list and not operands)
			or (operator == "between" and len(operands) != 2)
			or (operator == "is" and operand not in ("set", "not set"))
			or any(
				not isinstance(entry, (str, int, float, bool, type(None)))
				or (isinstance(entry, float) and not math.isfinite(entry))
				for entry in operands
			)
		):
			invalid()
		conditions.append((fieldname, operator, operand))
	return conditions


def readable_levels(meta, user: str) -> set[int] | None:
	"""Return the permission levels the user may read on the DocType; None means every level."""
	if user == "Administrator":
		return None
	roles = set(frappe.get_roles(user))
	return {
		permission.permlevel
		for permission in meta.get_permissions()
		if permission.role in roles and permission.read and not permission.if_owner
	}


def check_readable(meta, user: str, fieldnames: list, invalid, parenttype: str | None = None) -> None:
	"""Reject a malformed field name and deny a field the user cannot read.

	A child table takes its read levels from the parent DocType named in parenttype.
	"""
	valid_columns = set(meta.get_valid_columns())
	permitted = set(
		get_permitted_fields(
			meta.name, parenttype=parenttype, user=user, permission_type="read", ignore_virtual=True
		)
	)
	masked = {field.fieldname for field in meta.get_masked_fields()}
	read_levels = readable_levels(frappe.get_meta(parenttype) if parenttype else meta, user)

	for fieldname in fieldnames:
		if (
			not isinstance(fieldname, str)
			or not re.fullmatch(FIELD_PATTERN, fieldname)
			or fieldname not in valid_columns
		):
			invalid()
		field = meta.get_field(fieldname)
		if (
			fieldname not in permitted
			or fieldname in masked
			or (field and field.fieldtype == "Password")
			or (field and field.permlevel and read_levels is not None and field.permlevel not in read_levels)
		):
			raise frappe.PermissionError


def check_fields(meta, user: str, query: SummaryQuery, conditions: list[tuple]) -> None:
	requested_fields = [query.group_by, *(item[0] for item in conditions)]
	if query.aggregate_field:
		requested_fields.append(query.aggregate_field)
	check_readable(meta, user, requested_fields, invalid_query)
	if query.aggregate_field:
		field = meta.get_field(query.aggregate_field)
		if not field or field.fieldtype not in numeric_fieldtypes:
			invalid_query()


def read_summary(query: SummaryQuery, user: str) -> dict:
	if not frappe.db.exists("DocType", query.doctype):
		raise frappe.DoesNotExistError
	meta = frappe.get_meta(query.doctype)
	frappe.has_permission(query.doctype, "read", user=user, throw=True)
	if meta.istable or meta.issingle or meta.is_virtual:
		invalid_query()
	conditions = filter_rows(query.filters, query.doctype)
	check_fields(meta, user, query, conditions)

	fields = list(dict.fromkeys(field for field in (query.group_by, query.aggregate_field) if field))
	permitted_query = frappe.qb.get_query(
		query.doctype, fields=fields, filters=conditions, ignore_permissions=False, user=user
	)
	# Match native list controller restrictions before collecting statistics.
	controller = get_controller(query.doctype)
	if controller_list := getattr(controller, "get_list", None):
		if restricted_query := controller_list(permitted_query):
			permitted_query = restricted_query

	visible_rows = permitted_query.as_("visible_rows")
	grouping_field = visible_rows[query.group_by]
	group_count = functions.Count("*")
	total_count = AnalyticFunction("SUM", group_count).over()
	grouped_query = (
		frappe.qb.from_(visible_rows)
		.select(grouping_field.as_("value"), group_count.as_("count"), total_count.as_("total_count"))
		.groupby(grouping_field)
		.orderby(grouping_field)
		.limit(query.limit + 1)
	)
	if query.aggregate_field:
		operation = functions.Sum if query.aggregate == "sum" else functions.Avg
		grouped_query = grouped_query.select(operation(visible_rows[query.aggregate_field]).as_("aggregate"))

	groups = grouped_query.run(as_dict=True)
	total = int(groups[0]["total_count"]) if groups else 0
	for group in groups:
		group.pop("total_count")
	return {"groups": groups[: query.limit], "total_count": total, "truncated": len(groups) > query.limit}


def read_list_query() -> ListQuery:
	request_params = {
		key: argument for key, argument in frappe.form_dict.items() if key not in FRAMEWORK_PARAMETERS
	}
	try:
		return ListQuery.model_validate(request_params)
	except QueryValidationError:
		invalid_list()


def list_fields(raw_fields: str | None) -> list[str]:
	if raw_fields is None:
		return ["name"]
	try:
		fields = json.loads(raw_fields)
	except ValueError:
		invalid_list()
	if not isinstance(fields, list) or not fields or len(fields) > 100:
		invalid_list()
	return fields


def list_order(raw_order: str | None, default: str) -> tuple[str, list[str]]:
	if raw_order is None:
		return default, [default.split()[0]]
	parts = [part.strip() for part in raw_order.split(",")]
	matches = [re.fullmatch(ORDER_PATTERN, part, flags=re.IGNORECASE) for part in parts]
	if len(parts) > 5 or not all(matches):
		invalid_list()
	terms = [f"{match[1]} {(match[2] or 'asc').lower()}" for match in matches]
	return ", ".join(terms), [match[1] for match in matches]


def child_scope(query: ListQuery, conditions: list[tuple], user: str) -> str:
	"""Return the one parent record whose rows the request reads, after its permission check."""
	parent = query.parent
	if not parent or not frappe.db.exists("DocType", parent):
		invalid_list()
	parent_meta = frappe.get_meta(parent)
	scope = {}
	for fieldname, operator, operand in conditions:
		if fieldname in CHILD_SCOPE and operator == "=" and isinstance(operand, str):
			scope.setdefault(fieldname, set()).add(operand)
	if any(len(scope.get(fieldname, ())) != 1 for fieldname in CHILD_SCOPE):
		invalid_list()
	(parent_name,), (parenttype,), (parentfield,) = (scope[fieldname] for fieldname in CHILD_SCOPE)
	table = parent_meta.get_field(parentfield)
	if (
		parent_meta.istable
		or parenttype != parent
		or not table
		or table.fieldtype not in TABLE_FIELDTYPES
		or table.options != query.doctype
	):
		invalid_list()
	frappe.has_permission(parent, "read", user=user, throw=True)
	# A table field is not a database column, so check_readable cannot check it. Check its level here.
	read_levels = readable_levels(parent_meta, user)
	if read_levels is not None and table.permlevel not in read_levels:
		raise frappe.PermissionError
	if not frappe.db.exists(parent, parent_name):
		raise frappe.DoesNotExistError
	frappe.has_permission(parent, "read", doc=parent_name, user=user, throw=True)
	return parent


def read_list(query: ListQuery, user: str) -> list[dict]:
	"""Read one page of permitted rows; a child table is read only within one parent record."""
	if not frappe.db.exists("DocType", query.doctype):
		raise frappe.DoesNotExistError
	meta = frappe.get_meta(query.doctype)
	if meta.issingle or meta.is_virtual:
		invalid_list()
	conditions = filter_rows(query.filters, query.doctype, invalid_list)
	if meta.istable:
		parent = child_scope(query, conditions, user)
		default_order = "idx asc"
	else:
		if query.parent:
			invalid_list()
		frappe.has_permission(query.doctype, "read", user=user, throw=True)
		parent = None
		default_order = "creation desc"
	fields = list_fields(query.fields)
	order_by, order_fields = list_order(query.order_by, default_order)
	check_readable(
		meta, user, [*fields, *(item[0] for item in conditions), *order_fields], invalid_list, parent
	)

	return frappe.get_list(
		query.doctype,
		fields=fields,
		filters=conditions,
		order_by=order_by,
		limit_start=query.limit_start,
		limit_page_length=min(query.limit_page_length, MAX_PAGE_LENGTH),
		parent_doctype=parent,
		user=user,
	)
