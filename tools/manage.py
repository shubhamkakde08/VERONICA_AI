"""Admin helper (run inside the container):

  python -m tools.manage init                                   create tables + first admin
  python -m tools.manage add-user "Ramesh Patel" manager [telegram_id] [username password]
  python -m tools.manage set-login 3 ramesh StrongPass123      give / reset web username + password
  python -m tools.manage users                                  list users
  python -m tools.manage disable 3      |  enable 3             block / unblock a user (logs them out)
  python -m tools.manage logout-all 3                           sign a user out on every device
  python -m tools.manage seed-skills [file.json | folder]       load report skills (default examples/skills)
  python -m tools.manage set-webhook                            register Telegram webhook
  python -m tools.manage run-schedule 3                         run a schedule now
  python -m tools.manage voices hi-IN                           list Gemini female voices for a language
  python -m tools.manage say "Namaste, main Veronica hoon"      test the voice (writes voice_test.mp3)
  python -m tools.manage boss-voice [--again] [gemini]          record the admin "Hello Boss" lines once in VERONICA's voice
  python -m tools.manage columns VIEW_REJECTION_PBI            show columns + comments exactly as the bot sees them
  python -m tools.manage dept-roles                             create department roles: production, purchase, sales, accounts, quality, stores
  python -m tools.manage roles                                  list roles + the views each may read
  python -m tools.manage add-role production "VIEW_TUBING_PBI,VIEW_SCRAP_*" ["Production dept"]   custom role
  python -m tools.manage add-role prod_stock "production,VIEW_ITEM_LEDGER_PBI"   mix roles + views (role names expand)
  python -m tools.manage set-role 5 production                  change user #5's role
  python -m tools.manage delete-user 3                          delete user #3 for good (asks to confirm)
  python -m tools.manage rename-user 7 "Kunal Bubna"            change a user's name
  python -m tools.manage set-themes 5 titan,nova                 user #5 may use only these looks (none = all)
  python -m tools.manage set-division 5 U2        user #5 sees only U2 (Seamless) data in every report  (ALL = remove)
  python -m tools.manage set-contact 5 user@yourcompany.com 9876543210   e-mail / WhatsApp number of user #5 (for "send it to Ravi")
  python -m tools.manage set-telegram 5 987654321               link a Telegram id to an existing user #5
  python -m tools.manage export-users [users.xlsx]              Excel: users, role, department, Telegram, login, views, reports
  python -m tools.manage check-scrap-mis 2026-10                 Scrap MIS: per view - columns used, date type, rows in that month
  python -m tools.manage skills                                 list reports + who may use them
  python -m tools.manage skill-access final_production_rejection_report manager,qa   only these roles (admin always)
  python -m tools.manage skill-access final_production_rejection_report all          open to everyone again
"""
import json
import sys

PRIVATE = "!VIEW_EMP_MAST_PBI"
DEPT_ROLES = {   # department -> views it may read (glob * allowed). Edit and re-run dept-roles to change.
    "production": ("Production dept - production, scrap, rejection, tubing, LSAW, slitting, welding", [
        "VIEW_JOB_CARD_SCRAP_PBI", "VIEW_JOB_CARDWISE_PROD_PBI", "VIEW_JOB_CARDWISE_SCRAP_PBI", "VIEW_PROD_PBI", "VIEW_PROD_PROC_PBI", "VIEW_TUBING_PBI",
        "VIEW_WELDED_TUBING_PBI", "VIEW_LSAW_PBI", "VIEW_SLITTING_PBI", "VIEW_WELD_COND_PBI", "VIEW_CUTTING_SCRAP_PBI",
        "VIEW_WELDED_SCRAP_PBI", "VIEW_SCRAP_*", "VIEW_REJECTION_PBI", "VIEW_FINAL_PROD_PBI",
        "VIEW_WELDED_SCRAP_MIS_PBI", "VIEW_SEAMLESS_SCRAP_MIS_PBI", "VIEW_SLITTING_MIS_PBI", "VIEW_FINAL_CUTTING_SCRAP_PBI", "VIEW_M2M_PBI"]),
    "quality": ("Quality dept - rejection, final inspection, scrap, weld conditions", [
        "VIEW_REJECTION_PBI", "VIEW_FINAL_PROD_PBI", "VIEW_JOB_CARD_SCRAP_PBI", "VIEW_JOB_CARDWISE_PROD_PBI", "VIEW_SCRAP_*", "VIEW_CUTTING_SCRAP_PBI",
        "VIEW_WELDED_SCRAP_PBI", "VIEW_WELD_COND_PBI", "VIEW_WELDED_SCRAP_MIS_PBI", "VIEW_SEAMLESS_SCRAP_MIS_PBI", "VIEW_SLITTING_MIS_PBI",
        "VIEW_FINAL_CUTTING_SCRAP_PBI", "VIEW_M2M_PBI"]),
    "purchase": ("Purchase dept - purchase orders, GRN, stock ledger", [
        "VIEW_PURCHASE_ORDER_ORDI_PBI", "VIEW_GRN_PBI", "VIEW_ITEM_LEDGER_PBI"]),
    "stores": ("Stores dept - GRN and stock movement", ["VIEW_GRN_PBI", "VIEW_ITEM_LEDGER_PBI"]),
    "sales": ("Sales / marketing - orders, invoices, quotations", [
        "VIEW_SALES_ORDER_PBI", "VIEW_LD_SALES_ORDERS_PBI", "VIEW_SALE_INVOICE_PBI", "VIEW_PENDING_QTNS_ENG_PBI"]),
    "accounts": ("Accounts - every report (employee master stays private)", ["*"]),
}
from pathlib import Path

from app import config, store


def _web_hint(u: dict) -> str:
    if config.WEB_REQUIRE_PASSWORD:
        if u.get("username"):
            return f"Web login: {config.PUBLIC_BASE_URL}/  (username: {u['username']})"
        return (f"Web login not set yet. Run:  python -m tools.manage set-login {u['id']} "
                f"<username> <password>")
    return f"Web link: {config.PUBLIC_BASE_URL}/?token={u['web_token']}"


def main(argv):
    if not argv:
        print(__doc__)
        return
    cmd, args = argv[0], argv[1:]
    store.init_db()
    try:
        if cmd == "init":
            for u in store.list_users():
                print(f"#{u['id']} {u['name']} ({u['role']})  {_web_hint(u)}")
        elif cmd == "add-user":
            name, role = args[0], args[1]
            tg = args[2] if len(args) > 2 and args[2].isdigit() else None
            rest = args[3:] if tg else args[2:]
            u = store.add_user(name, role, tg)
            if len(rest) >= 2:
                store.set_login(u["id"], rest[0], rest[1])
                u = store.get_user(u["id"])
            print(f"Added #{u['id']} {u['name']} as {u['role']}\n{_web_hint(u)}")
        elif cmd == "set-login":
            uid, username, password = int(args[0]), args[1], args[2]
            store.set_login(uid, username, password)
            u = store.get_user(uid)
            print(f"Login set for #{uid} {u['name']}\n{_web_hint(u)}\n"
                  f"Send the password to {u['name']} privately; they can change it after logging in.")
        elif cmd == "users":
            print(f"{'id':<4} {'name':<22} {'role':<11} {'username':<16} {'telegram':<12} {'division':<8} active")
            for u in store.list_users():
                print(f"{u['id']:<4} {u['name'][:22]:<22} {u['role'][:11]:<11} {(u.get('username') or '-'):<16} "
                      f"{(u['telegram_id'] or '-'):<12} {(u.get('division') or 'ALL'):<8} {bool(u['active'])}")
        elif cmd in ("disable", "enable"):
            uid = int(args[0])
            if uid == 1 and cmd == "disable":
                print("Refusing to disable the main admin (id 1).")
                return
            store.set_active(uid, cmd == "enable")
            print(f"User #{uid} {'enabled' if cmd == 'enable' else 'disabled and logged out'}.")
        elif cmd == "logout-all":
            store.end_all_sessions(int(args[0]))
            print(f"User #{args[0]} signed out everywhere.")
        elif cmd == "seed-skills":
            target = Path(args[0]) if args else Path(__file__).resolve().parent.parent / "examples/skills"
            for f in ([target] if target.suffix == ".json" else sorted(target.glob("*.json"))):
                s = store.save_skill(json.loads(f.read_text(encoding="utf-8")), changed_by="seed")
                print(f"/{s['name']} v{s['version']}")
        elif cmd == "set-webhook":
            from app import telegram
            print(telegram.set_webhook() if config.TELEGRAM_ENABLED else "Telegram is switched off (TELEGRAM_ENABLED=false) - webhook not set")
            telegram.set_commands()
        elif cmd == "voices":
            from app import voice
            for v in voice.list_voices(args[0] if args else "hi-IN", args[1] if len(args) > 1 else "female"):
                print(json.dumps(v, ensure_ascii=False))
        elif cmd == "say":
            from app import voice
            out = Path("voice_test.mp3")
            out.write_bytes(voice.speak(" ".join(args) or "Namaste! Main Veronica hoon. Aaj main aapki kya madad kar sakti hoon?"))
            print(f"Saved {out.resolve()} - play it to hear the voice ({config.GEMINI_VOICE}).")
        elif cmd == "boss-voice":
            from app import voice
            from app.greetings import BOSS_LINES
            folder = Path(__file__).resolve().parent.parent / "app" / "static" / "boss"
            folder.mkdir(parents=True, exist_ok=True)
            for i, line in enumerate(BOSS_LINES, 1):
                out = folder / f"hello_{i}.mp3"
                if out.exists() and "--again" not in args:
                    print(f"hello_{i}.mp3 already recorded"); continue
                try:
                    out.write_bytes(voice.speak(line, "en-IN", engine="gemini" if "gemini" in args else None))
                    print(f"Recorded hello_{i}.mp3")
                except Exception as e:
                    print(f"Could not record hello_{i}.mp3 now: {e}")
                    print("If this used Gemini, its daily voice limit is probably used up - run again after it resets.")
                    break
        elif cmd == "columns":
            from app import datadb
            for t in datadb.describe_tables([args[0]], ["*"]):
                if t.get("error"):
                    print(f"{t['table']}: {t['error']}")
                    continue
                print(f"{t['table']}" + (f"  -- {t['comment']}" if t.get("comment") else ""))
                for c in t["columns"]:
                    print(f"  {c['name']:<32} {c['type']:<18} {c.get('comment') or '(no comment)'}")
                if not any(c.get("comment") for c in t["columns"]):
                    print("No comments yet - run the Oracle sync once (it now copies comments), then try again.")
        elif cmd == "dept-roles":
            for name, (desc, views) in DEPT_ROLES.items():
                store.save_role(name, views + [PRIVATE], desc, free_query=True)
                print(f"{name:<11} {desc}")
            print("\nDone. Add a user:  add-user \"Bharat Prajapati\" production <telegram_id>")
        elif cmd == "roles":
            for r in store.list_roles():
                flags = "admin" if r.get("is_admin") else ("teach " if r.get("can_teach") else "") + ("schedule" if r.get("can_schedule") else "")
                print(f"{r['name']:<11} {flags:<15} {', '.join(r.get('allowed_tables') or []) or '(nothing)'}")
        elif cmd == "add-role":
            views, roles_now = [], {r["name"]: r for r in store.list_roles()}
            for v in (x.strip() for x in args[1].split(",") if x.strip()):
                if v.lower() in roles_now and v.lower() != args[0].lower():   # a role name -> all its views
                    views += [t for t in roles_now[v.lower()]["allowed_tables"] or [] if t not in views]
                elif v not in views:
                    views.append(v)
            if PRIVATE not in views:
                views.append(PRIVATE)
            r = store.save_role(args[0], views, args[2] if len(args) > 2 else "")
            print(f"{r['name']}: {', '.join(r['allowed_tables'])}")
        elif cmd == "set-role":
            store.set_user_role(int(args[0]), args[1].lower())
            print(f"user #{args[0]} -> {args[1].lower()} (takes effect on the next message)")
        elif cmd == "rename-user":
            store.rename_user(int(args[0]), " ".join(args[1:]))
            u = store.get_user(int(args[0]))
            print(f"#{u['id']} renamed to {u['name']}")
        elif cmd == "set-contact":
            em = next((a for a in args[1:] if "@" in a), None)
            ph = next((a for a in args[1:] if "@" not in a), None)
            store.set_user_contact(int(args[0]), email=em, phone=ph)
            u = store.get_user(int(args[0]))
            print(f"#{u['id']} {u['name']}: email={u.get('email') or '-'} whatsapp={u.get('phone') or '-'}")
        elif cmd == "delete-user":
            u = store.get_user(int(args[0]))
            if not u:
                raise ValueError(f"no user #{args[0]}")
            if "--yes" not in args and input(f"Delete #{u['id']} {u['name']} ({u['role']})? type YES: ").strip() != "YES":
                print("cancelled")
                return
            store.delete_user(u["id"])
            print(f"deleted #{u['id']} {u['name']}")
        elif cmd == "set-themes":
            got = store.set_user_themes(int(args[0]), args[1] if len(args) > 1 else "")
            print(f"#{args[0]} may use: {', '.join(got)}")
        elif cmd == "set-division":
            store.set_user_division(int(args[0]), args[1] if len(args) > 1 else "")
            u = store.get_user(int(args[0]))
            print(f"#{u['id']} {u['name']}: " + (f"sees ONLY {u['division']} division data" if u.get("division") else "sees all divisions"))
        elif cmd == "set-telegram":
            store.set_user_telegram(int(args[0]), args[1])
            print(f"user #{args[0]} linked to Telegram {args[1]}")
        elif cmd == "export-users":
            from openpyxl import Workbook
            from openpyxl.styles import Alignment, Font, PatternFill
            from openpyxl.utils import get_column_letter
            out = Path(args[0] if args else "users.xlsx").resolve()
            roles_d = {r["name"]: r for r in store.list_roles()}
            wb = Workbook()
            head_font, head_fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="1F3A5F")

            def sheet(ws, header, rows, widths):
                ws.append(header)
                for r in rows:
                    ws.append(r)
                for c in ws[1]:
                    c.font, c.fill = head_font, head_fill
                for i, w in enumerate(widths, 1):
                    ws.column_dimensions[get_column_letter(i)].width = w
                for row in ws.iter_rows(min_row=2):
                    for c in row:
                        c.alignment = Alignment(wrap_text=True, vertical="top")
                ws.freeze_panes = "A2"
                ws.auto_filter.ref = ws.dimensions

            ws = wb.active; ws.title = "Users"
            urows = []
            for u in store.list_users():
                r = roles_d.get(u["role"], {})
                reps = ", ".join(sk["title"] for sk in store.list_skills(u))
                urows.append([u["id"], u["name"], u["role"], r.get("description") or "", u.get("telegram_id") or "",
                              u.get("username") or "", "Active" if u.get("active", True) else "Disabled",
                              ", ".join(t for t in r.get("allowed_tables") or [] if not t.startswith("!")) or "-",
                              reps or "-", str(u.get("created_at") or "")[:16]])
            sheet(ws, ["#", "Name", "Role", "Department / access", "Telegram ID", "Web username", "Status",
                       "Views allowed", "Reports available", "Created"], urows, [5, 24, 14, 34, 14, 16, 10, 60, 40, 17])
            ws2 = wb.create_sheet("Roles")
            sheet(ws2, ["Role", "Department / access", "Views allowed", "Blocked", "Admin", "Teach", "Schedule", "Users"],
                  [[n, r.get("description") or "", ", ".join(t for t in r.get("allowed_tables") or [] if not t.startswith("!")),
                    ", ".join(t[1:] for t in r.get("allowed_tables") or [] if t.startswith("!")),
                    "Yes" if r.get("is_admin") else "", "Yes" if r.get("can_teach") else "", "Yes" if r.get("can_schedule") else "",
                    sum(1 for u in store.list_users() if u["role"] == n)] for n, r in roles_d.items()],
                  [14, 40, 70, 22, 7, 7, 9, 7])
            wb.save(out)
            print(f"Saved {out}  ({len(urows)} users, {len(roles_d)} roles). Passwords are never exported.")
        elif cmd == "check-scrap-mis":
            import calendar as _cal
            import datetime as _dt
            from app.engines import scrap_mis as sm
            y, m = (int(x) for x in (args[0] if args else _dt.date.today().strftime("%Y-%m")).split("-")[:2])
            d1, d2 = _dt.date(y, m, 1), _dt.date(y, m, _cal.monthrange(y, m)[1])
            sk = store.get_skill("scrap_mis_report")
            st = json.loads((sk or {}).get("sql_template") or "{}")
            sources = {**sm.DEFAULT_SOURCES, **(st.get("sources") or {})}
            for slot, src in sources.items():
                if not src:
                    continue
                sm.DIAG.clear()
                try:
                    raw, cols, _ = sm.fetch(src, sm.KIND_OF[slot], d1, d2, ["*"])
                    recs = sm.to_records(sm.KIND_OF[slot], raw, cols)
                    g = sm.DIAG.get(src, {})
                    print(f"\n[{slot}] {src}\n  columns used : {cols}\n  date column  : {g.get('date_column')}  type={g.get('date_type')}  filter={g.get('date_filter')}"
                          f"\n  rows {d1:%b %Y}: fetched {len(raw)}, used {len(recs)}" + (f"\n  date sample  : {g.get('sample')}" if g.get("sample") else ""))
                    if recs:
                        k = "plant" if sm.KIND_OF[slot] == "process" else "name" if slot == "cutting" else "group"
                        vals = sorted({str(r.get(k)) for r in recs})[:15]
                        print(f"  {k} values : {vals}")
                except Exception as e:
                    print(f"\n[{slot}] {src}\n  ERROR: {e}")
        elif cmd == "skills":
            for sk in store.list_skills():
                print(f"/{sk['name']:<40} {', '.join(sk.get('allowed_roles') or []) or 'everyone'}")
        elif cmd == "skill-access":
            sk = store.get_skill(args[0])
            if not sk:
                raise ValueError(f"no report named {args[0]} (see: skills)")
            roles = [] if args[1].lower() in ("all", "everyone") else [r.strip() for r in args[1].split(",") if r.strip()]
            store.save_skill({"name": sk["name"], "allowed_roles": roles}, "manage")
            print(f"/{sk['name']} -> {', '.join(roles) or 'everyone'} (admins always)")
        elif cmd == "run-schedule":
            from app import scheduler
            scheduler.reload()
            print(scheduler.run_schedule(int(args[0])))
        else:
            print(__doc__)
    except (ValueError, IndexError) as e:
        print(f"Error: {e}\n\n{__doc__}")


if __name__ == "__main__":
    main(sys.argv[1:])
