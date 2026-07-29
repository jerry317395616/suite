import frappe
from pypika import CustomFunction, Order
from pypika import functions as fn

from suite.drive.utils import get_default_team, file_fields, STATUS_ACTIVE
from suite.drive.api.permissions import get_user_access
from suite.writer.search import WriterSearch

Binary = CustomFunction("BINARY", ["expression"])


@frappe.whitelist()
def get_document_list(
    start: int = 0,
    limit: int = 20,
):
    user = frappe.session.user
    drive_file = frappe.qb.DocType("File")
    drive_permission = frappe.qb.DocType("Drive Permission")
    drive_favourite = frappe.qb.DocType("Drive Favourite")
    recents = frappe.qb.DocType("Drive Entity Log")

    recently_opened = (
        frappe.qb.from_(recents).select(recents.entity_name).where(recents.user == user)
    )

    recent_field = fn.Coalesce(recents.last_interaction, drive_file.file_modified)
    query = (
        frappe.qb.from_(drive_file)
        .select(
            *file_fields(),
            drive_file.mime_type,
            recent_field.as_("recent"),
        )
        .where((drive_file.status == STATUS_ACTIVE) & (drive_file.mime_type == "frappe_doc"))
        .where((drive_file.owner == user) | (drive_file.name.isin(recently_opened)))
    )

    query = (
        query.left_join(drive_favourite)
        .on((drive_favourite.entity == drive_file.name) & (drive_favourite.user == user))
        .select(drive_favourite.name.as_("is_favourite"))
    )

    query = query.left_join(recents).on(
        (recents.entity_name == drive_file.name) & (recents.user == frappe.session.user)
    )

    query = query.select(recents.last_interaction.as_("accessed"))

    # Add ordering
    query = query.orderby(recent_field, order=Order.desc)
    # Fetch one extra record to check if there's a next page
    query = query.limit(limit + 1).offset(start)
    res = query.run(as_dict=True)

    # Check if there's a next page
    has_next_page = len(res) > limit

    # Remove the extra record if it exists
    if has_next_page:
        res = res[:limit]

    # Rest of your processing code
    child_count_query = (
        frappe.qb.from_(drive_file)
        .where((drive_file.team == get_default_team()) & (drive_file.status == STATUS_ACTIVE))
        .select(drive_file.folder, fn.Count("*").as_("child_count"))
        .groupby(drive_file.folder)
    )
    share_query = (
        frappe.qb.from_(drive_file)
        .right_join(drive_permission)
        .on(drive_permission.entity == drive_file.name)
        .where((drive_permission.user != "") & (drive_permission.user != "$TEAM"))
        .select(drive_file.name, fn.Count("*").as_("share_count"))
        .groupby(drive_file.name)
    )
    public_files_query = (
        frappe.qb.from_(drive_permission)
        .where(drive_permission.user == "")
        .select(drive_permission.entity)
    )
    team_files_query = (
        frappe.qb.from_(drive_permission)
        .where(drive_permission.team == 1)
        .select(drive_permission.entity)
    )
    public_files = set(k[0] for k in public_files_query.run())
    team_files = set(k[0] for k in team_files_query.run())

    children_count = dict(child_count_query.run())
    share_count = dict(share_query.run())

    default = 0

    accessible = []
    for r in res:
        access = get_user_access(r["name"])
        # A stale "recently opened" entry can outlive the caller's access.
        if not access.get("read"):
            continue
        accessible.append(r)
        r["children"] = children_count.get(r["name"], 0)
        r["html"] = frappe.get_cached_value("Writer Document", r["content_docname"], "html")
        if r["name"] in public_files:
            r["share_count"] = -2
        elif default > -1 and (r["name"] in team_files):
            r["share_count"] = -1
        elif default == 0:
            r["share_count"] = share_count.get(r["name"], default)
        else:
            r["share_count"] = default
        r |= access

    # Return in the format useList expects
    frappe.response["data"] = accessible
    frappe.response["has_next_page"] = has_next_page


@frappe.whitelist()
def get_versions(id: str):
    if not get_user_access(id).get("write"):
        frappe.throw("You don't have write access.", frappe.PermissionError)

    doc_name = frappe.db.get_value("File", id, "content_docname")

    versions = frappe.get_all(
        "Writer Version",
        filters={"doc": doc_name},
        fields=["name", "snapshot", "title", "manual", "creation"],
        order_by="creation asc",
    )

    return versions


@frappe.whitelist()
def search(query: str, filters: str | None = None):
    client = WriterSearch()
    search = client.search(query, filters=filters)
    metadata = get_drive_file_meta([k["name"] for k in search["results"]])
    cleaned_results = []
    for k in search["results"]:
        meta = metadata.get(k["name"])
        # The index is unscoped; only surface documents the caller can read.
        if not meta or not get_user_access(meta["name"]).get("read"):
            continue
        k.update(meta)
        cleaned_results.append(k)
    search["results"] = cleaned_results
    return search


def get_drive_file_meta(names, ttl=3600):
    """
    Fetch {name: {title, file_id}} using Redis first, DB as fallback.
    """
    if not names:
        return {}

    cache = frappe.cache()

    keys = {name: f"search:drive_file:{name}" for name in names}
    cached = {"name": cache.get_value(k) for k in keys.values()}

    result = {}
    missing = []
    for name, key in keys.items():
        value = cached.get(key)
        if value:
            result[name] = value
        else:
            missing.append(name)

    if missing:
        rows = frappe.get_all(
            "File",
            filters={"content_docname": ["in", missing], "content_doctype": "Writer Document"},
            fields=["name", "file_name", "content_docname"],
        )

        for r in rows:
            meta = {
                "title": r["file_name"],
                "name": r["name"],
            }
            key = f"search:drive_file:{r['name']}"
            cache.set_value(key, meta, expires_in_sec=ttl)
            result[r["content_docname"]] = meta

    return result
