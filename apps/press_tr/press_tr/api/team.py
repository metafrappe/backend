import frappe
from frappe import _

from press_tr.press_identity.customer import team_admin
from press_tr.press_identity.disposable_email import reject_disposable
from press_tr.press_identity.invitations import preview_invitation

MAX_NAME_LENGTH = 150
# The same limits as the `Email` schema of contracts/identity_sync.openapi.yaml.
MAX_LOCAL_PART = 64
MAX_DOMAIN = 189


@frappe.whitelist(methods=["POST"])
def invite(email: str, first_name: str = "", last_name: str = "") -> dict:
	# G-16, G-79: Press's own e-mail keyed invitation stays closed. identity-sync previews the
	# invitation here. Only the approval layer executes it (contracts/identity_sync.openapi.yaml).
	team = team_admin({"email", "first_name", "last_name"})
	email = _valid_email(email)
	reject_disposable(email)
	names = [first_name, last_name]
	if not all(isinstance(name, str) and len(name) <= MAX_NAME_LENGTH for name in names):
		frappe.throw(_("The name is too long.", context="press_tr"), frappe.ValidationError)
	organization_id = getattr(team, "custom_ptr_keycloak_org_id", None)
	return preview_invitation(email, first_name.strip(), last_name.strip(), organization_id)


def _valid_email(email) -> str:
	if isinstance(email, str):
		email = email.strip().lower()
		local, at, domain = email.partition("@")
		if (
			at
			and 1 <= len(local) <= MAX_LOCAL_PART
			and 1 <= len(domain) <= MAX_DOMAIN
			and "@" not in domain
			and not any(character.isspace() for character in email)
		):
			return email
	frappe.throw(_("Enter a valid email address.", context="press_tr"), frappe.ValidationError)
