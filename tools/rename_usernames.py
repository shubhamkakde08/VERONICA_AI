"""RENAME_USERNAMES.bat - change web login names (passwords, roles, divisions and history are kept).
Edit RENAMES below for future changes. Matching: exact current username first, else the one user whose
name starts with that word."""
from app import store

RENAMES = [("dwarika", "DWARGUP"), ("kk", "KUNAKHOT"), ("subrat", "SUBRJEN"), ("bharat", "BHARPRA"),
           ("ravi", "RAVICHO"), ("sandeep", "SANDSHE"), ("jayash", "JAYGAMI")]


def find(old: str, users: list[dict]):
    o = old.lower()
    exact = [u for u in users if (u.get("username") or "").lower() == o]
    if exact:
        return exact[0], ""
    by_name = [u for u in users if (u.get("name") or "").lower().split()[:1] == [o] or (u.get("name") or "").lower().startswith(o + " ")]
    if len(by_name) == 1:
        return by_name[0], " (matched by name)"
    if len(by_name) > 1:
        return None, "more than one user is called " + old + ": " + ", ".join(f"#{u['id']} {u['name']}" for u in by_name)
    return None, "no user with username or first name '" + old + "'"


def main():
    store.init_db()                       # adds any new columns first (safe to run before a restart)
    users = store.list_users()
    ok = 0
    for old, new in RENAMES:
        if any((u.get("username") or "") == new.lower() for u in users):
            print(f"  = {new:<9} already set"); ok += 1; continue
        u, note = find(old, users)
        if not u:
            print(f"  ! {old:<9} -> {new:<9} NOT changed: {note}"); continue
        try:
            got = store.rename_username(u["id"], new)
            print(f"  + #{u['id']:<3} {u['name'][:24]:<24} {u.get('username') or '-':<10} -> {got.upper()}{note}"); ok += 1
            u["username"] = got
        except ValueError as e:
            print(f"  ! {old:<9} -> {new:<9} NOT changed: {e}")
    print(f"\n{ok} of {len(RENAMES)} done. Users now type the new name to sign in (capitals don't matter); passwords are unchanged.")


if __name__ == "__main__":
    main()
