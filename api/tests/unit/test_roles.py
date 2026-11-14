from app import roles
from app.roles import CAPABILITIES, ROLES


def test_ranks_rise_from_viewer_to_owner():
    assert [r.key for r in sorted(ROLES.values(), key=lambda r: r.rank)] == ["viewer", "operator", "admin", "owner"]


def test_each_role_includes_everything_below_it():
    ordered = sorted(ROLES.values(), key=lambda r: r.rank)
    for lower, higher in zip(ordered, ordered[1:]):
        assert lower.capabilities < higher.capabilities


def test_the_catalog_is_what_the_directory_is_sent():
    cat = roles.catalog()["roles"]
    assert [r["key"] for r in cat] == ["viewer", "operator", "admin", "owner"]
    owner = cat[-1]
    assert owner["site_limitable"] is False and set(owner["capabilities"]) == set(CAPABILITIES)
    assert owner["sensitive_capabilities"] == ["entry.credential.issue", "entry.door.unlock", "entry.emergency.open", "entry.lockdown",
                                               "entry.visitors.manage"]
    assert cat[1]["sensitive_capabilities"] == ["entry.door.unlock", "entry.lockdown", "entry.visitors.manage"]


def test_only_the_owner_can_open_every_door_at_once_or_read_the_audit_trail():
    assert {k for k, r in ROLES.items() if "entry.emergency.open" in r.capabilities} == {"owner"}
    assert {k for k, r in ROLES.items() if "entry.audit.view" in r.capabilities} == {"owner"}


def test_operators_open_doors_but_never_issue_credentials():
    op = ROLES["operator"].capabilities
    assert "entry.door.unlock" in op and "entry.lockdown" in op and "entry.credential.issue" not in op and "entry.config.manage" not in op


def test_the_hash_is_stable_and_changes_with_the_catalog(monkeypatch):
    first = roles.catalog_hash()
    assert first == roles.catalog_hash()
    monkeypatch.setitem(roles.ROLES, "viewer", roles.RoleDef("viewer", "Viewer", 1, True, frozenset()))
    assert roles.catalog_hash() != first
