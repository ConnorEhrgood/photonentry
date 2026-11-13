from sqlalchemy import text


def test_the_migration_ran_and_the_roles_are_restricted(db):
    assert db.execute(text("select current_user")).scalar() == "entry_system"
    r = db.execute(text("select rolsuper, rolbypassrls from pg_roles where rolname = 'entry_app'")).one()
    assert tuple(r) == (False, False)
