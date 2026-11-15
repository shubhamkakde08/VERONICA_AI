"""Interactive helper behind SET_DIVISION.bat - forgiving input ("13", "13 Bharat", "u2", "U2 (Seamless)")."""
import re

from app import store


def ask(prompt, parse):
    while True:
        v = parse(input(prompt))
        if v is not None:
            return v
        print("   Sorry, I did not understand that - please try again.\n")


def main():
    users = {u["id"]: u for u in store.list_users()}
    print(f"\n{'id':<4} {'name':<22} {'role':<11} division")
    for u in users.values():
        print(f"{u['id']:<4} {u['name'][:22]:<22} {u['role'][:11]:<11} {u.get('division') or 'ALL'}")
    print()

    def pid(s):
        m = re.search(r"\d+", s or "")
        return int(m.group()) if m and int(m.group()) in users else None

    def pdiv(s):
        t = (s or "").upper()
        for d in ("U1", "U2", "ALL"):
            if d in t:
                return d
        if "WELD" in t:
            return "U1"
        if "SEAM" in t:
            return "U2"
        if "BOTH" in t:
            return "ALL"
        return None

    uid = ask("User id (the number in the first column): ", pid)
    print(f"   -> {users[uid]['name']}")
    div = ask("Division - type U1 (Welded only), U2 (Seamless only) or ALL (both): ", pdiv)
    store.set_user_division(uid, "" if div == "ALL" else div)
    u = store.get_user(uid)
    print(f"\nSaved: {u['name']} now sees " + (f"ONLY {u['division']} ({'Welded' if u['division'] == 'U1' else 'Seamless'}) data."
                                                if u.get("division") else "ALL divisions."))


if __name__ == "__main__":
    main()
