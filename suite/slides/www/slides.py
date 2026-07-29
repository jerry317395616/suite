import frappe

no_cache = 1


def get_context(context):
	csrf_token = frappe.sessions.get_csrf_token()
	# Persist the generated CSRF/session state before rendering the page.
	frappe.db.commit()  # nosemgrep: frappe-manual-commit
	context.csrf_token = csrf_token
	context.apps = frappe.get_installed_apps()
	context.site_name = frappe.local.site
