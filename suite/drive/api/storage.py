import frappe
from frappe import _
from pypika import functions as fn

from suite.drive.api.permissions import get_teams
from suite.drive.utils import STATUS_ACTIVE, default_team

MEGA_BYTE = 1024**2


@frappe.whitelist()
def storage_breakdown(team: str, owned_only: bool):
	drive_file = frappe.qb.DocType("File")
	if team not in get_teams():
		frappe.throw(_("You don't have access to this team."), frappe.PermissionError)

	limit = frappe.get_value("Drive Team", team, "quota" if owned_only else "storage") * MEGA_BYTE
	filters = {
		"team": team,
		"is_folder": False,
		"status": STATUS_ACTIVE,
		"file_size": [">=", limit / 200],
	}
	if owned_only:
		filters["owner"] = frappe.session.user

	entities = frappe.db.get_list(
		"File",
		filters=filters,
		order_by="file_size desc",
		fields=["name", "file_name", "owner", "file_size", "file_type"],
	)

	query = (
		frappe.qb.from_(drive_file)
		.select(drive_file.file_type, fn.Sum(drive_file.file_size).as_("file_size"))
		.where((drive_file.is_folder == 0) & (drive_file.status == STATUS_ACTIVE) & (drive_file.team == team))
	)
	if owned_only:
		query = query.where(drive_file.owner == frappe.session.user)

	return {
		"limit": limit,
		"total": query.groupby(drive_file.file_type).run(as_dict=True),
		"entities": entities,
	}


@frappe.whitelist()
@default_team
def storage_bar_data(team: str | None = None, entity_name: str | None = None):
	if not team:
		team = frappe.get_value("File", entity_name, "team")
		if not team:
			frappe.throw("Could not find team.", ValueError)

	if team not in get_teams():
		frappe.throw(_("You don't have access to this team."), frappe.PermissionError)

	return get_storage_usage(team)


def get_storage_usage(team: str):
	drive_file = frappe.qb.DocType("File")
	query = (
		frappe.qb.from_(drive_file)
		.where(
			(drive_file.team == team)
			& (drive_file.is_folder == 0)
			& (drive_file.owner == frappe.session.user)
			& (drive_file.status == STATUS_ACTIVE)
		)
		.select(fn.Coalesce(fn.Sum(drive_file.file_size), 0).as_("total_size"))
	)
	result = query.run(as_dict=True)[0]
	result["limit"] = frappe.get_value("Drive Team", team, "quota") * MEGA_BYTE
	return result
