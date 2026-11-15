"""SET_SCRAP_PLANTS.bat - who sees which Scrap MIS plant lines (and their division).
Users are found by new username, old username or first name. Edit PLANTS below for future changes,
or use VERONICA > your initials > Users: division & looks > Scrap MIS plants."""
from app import store

PLANTS = [
    # (names to find the user by,              division, plant lines)
    (("bharpra", "bharat"), "U2", ["S_PIPE1_EXP1", "S_PIPE1_PEEL", "S_PIPE1_PIL", "S_PIPE2_PEEL3", "S_PIPE2_PIL", "S_PIERC", "S_PIER2", "S_OTH"]),
    (("jaygami", "jayash"), "U2", ["S_BA", "S_TUBE"]),
    (("sandshe", "sandeep"), "U1", ["W_WELDED", "W_TM10", "W_COND", "W_SLIT", "L_LSAW"]),
]


def find(names, users):
    for n in names:
        hit = [u for u in users if (u.get("username") or "").lower() == n]
        if hit:
            return hit[0]
    for n in names:
        hit = [u for u in users if (u.get("name") or "").lower().split()[:1] == [n]]
        if len(hit) == 1:
            return hit[0]
    return None


def main():
    store.init_db()                       # adds any new columns first (safe to run before a restart)
    users = store.list_users()
    for names, div, lines in PLANTS:
        u = find(names, users)
        if not u:
            print(f"  ! {names[0].upper():<9} not found (looked for username/first name: {', '.join(names)})")
            continue
        store.set_user_division(u["id"], div)
        got = store.set_user_scrap_lines(u["id"], lines)
        print(f"  + #{u['id']:<3} {u['name'][:22]:<22} {div}  " + ", ".join(store.SCRAP_LINES[k] for k in got))
    print("\nApplies from each person's next Scrap MIS report or dashboard (no restart needed).")


if __name__ == "__main__":
    main()
