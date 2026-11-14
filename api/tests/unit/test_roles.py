from app import roles
from app.roles import CAPABILITIES, ROLES


def test_ranks_rise_from_door_user_to_owner():
    assert [r.key for r in sorted(ROLES.values(), key=lambda r: r.rank)] == ["door_user", "viewer", "operator", "admin", "owner"]
    assert min(r.rank for r in ROLES.values()) == 1                                    # the directory refuses a rank of 0


def test_each_role_includes_everything_below_it():
    ordered = sorted(ROLES.values(), key=lambda r: r.rank)
    for lower, higher in zip(ordered, ordered[1:]):
        assert lower.capabilities < higher.capabilities


def test_the_catalog_is_what_the_directory_is_sent():
    cat = roles.catalog()["roles"]
    assert [r["key"] for r in cat] == ["door_user", "viewer", "operator", "admin", "owner"]
    assert cat[0]["capabilities"] == ["entry.unlock.own"] and cat[0]["sensitive_capabilities"] == [] and cat[0]["site_limitable"] is True
    assert 0 < len(cat[0]["description"]) <= 200 and "description" not in cat[1]                        # photonid roles.schema.json (ee0637c)
    assert all("entry.unlock.own" in r["capabilities"] for r in cat)                  # promoting a door user never takes the app's unlock away
    owner = cat[-1]
    assert owner["site_limitable"] is False and set(owner["capabilities"]) == set(CAPABILITIES)
    assert owner["sensitive_capabilities"] == ["entry.credential.issue", "entry.door.unlock", "entry.emergency.open", "entry.lockdown",
                                               "entry.visitors.manage"]
    assert cat[2]["sensitive_capabilities"] == ["entry.door.unlock", "entry.lockdown", "entry.visitors.manage"]


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
