from __future__ import unicode_literals

import frappe

from suite.drive.api.permissions import user_has_permission

no_cache = 1


def get_context():
    csrf_token = frappe.sessions.get_csrf_token()
    # Persist the generated CSRF/session state before returning boot data.
    frappe.db.commit()  # nosemgrep: frappe-manual-commit
    context = frappe._dict()
    context.boot = get_boot()
    context.boot.csrf_token = csrf_token
    context.csrf_token = csrf_token
    context.site_name = frappe.local.site

    context.title = "Frappe Writer"
    context.description = "Open online."
    if not frappe.form_dict.app_path:
        return context

    # Parsing
    parts = frappe.form_dict.app_path.split("/")
    if parts[0] == "w":
        try:
            file = frappe.get_cached_doc("File", parts[1])
            if user_has_permission(file, "read"):
                context.title = file.file_name
                context.description = "By " + frappe.get_cached_value(
                    "User", file.owner, "full_name"
                )
        except:
            pass

    return context


@frappe.whitelist(methods=["POST"])
def get_context_for_dev():
    if not frappe.conf.developer_mode:
        frappe.throw("This method is only meant for developer mode")
    return get_boot()


def get_boot():
    return frappe._dict(
        {
            "frappe_version": frappe.__version__,
            "default_route": get_default_route(),
            "site_name": frappe.local.site,
            "read_only_mode": frappe.flags.read_only,
        }
    )


def get_default_route():
    return "/writer"
