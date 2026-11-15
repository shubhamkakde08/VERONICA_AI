"""LIST_USERS.bat - users, logins, roles, division, Scrap MIS plants, looks (no passwords or tokens)."""
from app import store


def main():
    store.init_db()
    print(f"{'#':<4}{'Name':<24}{'Login':<11}{'Role':<13}{'Div':<5}{'Active':<7}{'Scrap MIS plants':<18}Looks")
    for u in store.list_users():
        lines = store.user_scrap_lines(u)
        print(f"{u['id']:<4}{(u['name'] or '')[:23]:<24}{(u.get('username') or '-').upper():<11}{(u['role'] or '')[:12]:<13}"
              f"{(u.get('division') or 'ALL'):<5}{('yes' if u.get('active', True) else 'NO'):<7}"
              f"{(str(len(lines)) + ' plants' if lines else 'all'):<18}{','.join(store.user_themes(u))}")


if __name__ == "__main__":
    main()
