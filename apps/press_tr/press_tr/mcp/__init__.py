"""Commercial MCP server of press_tr (G-27).

The server runs beside Press's own `press.mcp.handler`. Its route is
`/api/method/press_tr.mcp.handler`. It accepts a request only when all of these hold:

- Press MCP is enabled (`Press Settings.enable_mcp`).
- The caller is the separate service account named in the site config key
  `press_tr_mcp_service_user`. The account is a System User with the System Manager role.
- The request comes from a network in the site config key `press_tr_mcp_allowed_networks`.
  An empty list refuses every request.

Every call, including a refused one, is written to the `PTR MCP Call` history.
"""

import frappe
import frappe_mcp

from press_tr.mcp import access, history

mcp = frappe_mcp.MCP("press-tr-mcp")


@mcp.register()
def handler():
	try:
		access.check_request()
	except frappe.AuthenticationError as error:
		history.record_refusal(str(error))
		raise

	import press_tr.mcp.tools

	_ = press_tr.mcp.tools
