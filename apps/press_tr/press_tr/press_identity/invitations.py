"""Ask identity-sync for a team invitation preview (G-16, G-79).

Press never executes an invitation. The approval layer sends the execute request with the
`preview_digest` and its `approval_id` (contracts/identity_sync.openapi.yaml, `/v1/invitations`).
"""

import frappe
import requests
from frappe import _
from werkzeug.exceptions import BadGateway, ServiceUnavailable

from press_tr.press_identity.deletion import service_token

CONNECT_TIMEOUT = 10
READ_TIMEOUT = 30


def preview_invitation(email: str, first_name: str, last_name: str, organization_id: str | None) -> dict:
	service_url = frappe.conf.identity_sync_url
	service_secret = frappe.conf.press_service_client_secret
	if not service_url or not service_secret or not organization_id:
		raise ServiceUnavailable(_("Configure the invitation service.", context="press_tr"))

	token = service_token(service_secret)
	try:
		response = requests.post(
			f"{service_url.rstrip('/')}/v1/invitations",
			headers={"Authorization": f"Bearer {token}"},
			json={
				"email": email,
				"first_name": first_name,
				"last_name": last_name,
				"organization_id": organization_id,
				"dry_run": True,
			},
			timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
			allow_redirects=False,
		)
		if response.status_code != 200:
			raise BadGateway()
		result = response.json()
	except (requests.RequestException, ValueError):
		raise BadGateway() from None
	if (
		not isinstance(result, dict)
		or not isinstance(result.get("previews"), list)
		or not isinstance(result.get("preview_digest"), str)
		or not (result.get("subject") is None or isinstance(result.get("subject"), str))
	):
		raise BadGateway()
	return {
		"subject": result["subject"],
		"previews": result["previews"],
		"preview_digest": result["preview_digest"],
	}
