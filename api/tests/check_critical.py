"""Fails unless every CRITICAL module has 100% line and branch coverage: anything that decides who may see or do what, what reaches a door
controller, or who a controller is. Run after a coverage run with a JSON report:  python api/tests/check_critical.py cov.json"""
import json
import sys

CRITICAL = [
    "api/app/access.py",                # roles and scopes
    "api/app/roles.py",                 # the role catalog
    "api/app/deps.py",                  # who is signed in, and their context in an organization
    "api/app/oidc.py",                  # token verification
    "api/app/rls.py",                   # who the database thinks it is talking to
    "api/app/sync.py",                  # keeping the directory copy; resolving a first sign-in
    "api/app/directory/projection.py",  # applying the directory's documents to our copy
    "api/app/crypto.py",                # card numbers and PINs at rest, and their fingerprints
    "api/app/document.py",              # what a site's settings may say
    "api/app/sitedoc.py",               # which people and credentials go into a site's settings
    "api/app/compiler/axis.py",         # what each controller is told
    "api/app/compiler/ical.py",
    "api/app/compiler/wiegand.py",
    "api/app/link/signing.py",          # who a controller is
    "api/app/link/service.py",          # what a controller may ask and is told
    "api/app/link/store.py",
    "api/app/link/pgstore.py",
]

data = json.load(open(sys.argv[1]))["files"]
bad = []
for path in CRITICAL:
    f = data.get(path)
    if f is None:
        bad.append(f"{path}: not measured")
        continue
    s = f["summary"]
    if s["missing_lines"] or s.get("missing_branches", 0) or s.get("num_partial_branches", 0):
        bad.append(f"{path}: {s['percent_covered']:.1f}% (missing lines {f['missing_lines']}, missing branches {f.get('missing_branches')})")
if bad:
    print("CRITICAL modules below 100% branch coverage:\n  " + "\n  ".join(bad))
    sys.exit(1)
print(f"critical modules at 100%: {len(CRITICAL)}")
