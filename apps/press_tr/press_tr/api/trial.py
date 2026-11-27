import frappe
from frappe import _

from press_tr.press_identity.customer import team_admin
from press_tr.press_identity.disposable_email import reject_disposable

MAX_PRODUCT_LENGTH = 140


@frappe.whitelist(methods=["POST"])
def start(product: str) -> dict[str, str | None]:
	# G-79: self sign-up opens only through this trial flow. Keycloak registration is closed.
	if not isinstance(product, str) or not 1 <= len(product) <= MAX_PRODUCT_LENGTH:
		frappe.throw(_("This Press request is not allowed.", context="press_tr"), frappe.PermissionError)
	team = team_admin({"product"})
	reject_disposable(frappe.session.user)
	if not frappe.db.get_value("Product Trial", product, "published"):
		frappe.throw(_("This trial product is not available.", context="press_tr"), frappe.DoesNotExistError)

	from press.api.product_trial import _get_or_create_site_request

	request = _get_or_create_site_request(product, team.name, None)
	return {
		"name": request.name,
		"site": request.site,
		"status": request.status,
		"product_trial": request.product_trial,
	}
