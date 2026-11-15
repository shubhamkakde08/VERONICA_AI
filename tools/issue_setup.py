"""ISSUE_SETUP.bat - one time: let every role open the Issue dashboard (division / plant locks still apply)
and show what VIEW_ISSUE_ENGINE_PBI holds (columns, divisions, plants). Prints no passwords or tokens."""
import json
from pathlib import Path

from app import datadb, store
from app.access import table_ok
from app.engines import issue

VIEW = issue.DEFAULT_SOURCE


def main():
    store.init_db()
    p = Path(__file__).resolve().parent.parent / "examples" / "skills" / "issue_dashboard.json"
    if not store.get_skill("issue_dashboard"):
        store.save_skill(json.loads(p.read_text(encoding="utf-8")), changed_by="seed")
        print("report skill issue_dashboard loaded")
    print("\nRoles:")
    for r in store.list_roles():
        tabs = list(r.get("allowed_tables") or [])
        if r.get("is_admin") or table_ok(VIEW, tabs):
            print(f"  {r['name']:<14} already can read {VIEW}")
            continue
        store.save_role(r["name"], tabs + [VIEW], r.get("description") or "", bool(r.get("can_teach")),
                        bool(r.get("can_schedule")), bool(r.get("free_query", True)), bool(r.get("is_admin")))
        print(f"  {r['name']:<14} + {VIEW}")
    try:
        datadb.refresh_schema_cache()
        names = list(datadb._all_tables())
        hits = [t for t in names if "ISSUE" in t.upper()]
        print(f"\nReplica database: {len(names)} tables/views. Names with ISSUE: {hits or 'NONE'}")
        if VIEW.lower() not in {t.lower() for t in names}:
            print(f"!! {VIEW} is NOT in the MySQL replica yet - add it to the Oracle -> MySQL sync, then run this again.")
    except Exception as e:
        print("could not list tables:", e)
    print(f"\n{VIEW}:")
    try:
        cols = issue.resolve(VIEW, ["*"])
        for f, c in cols.items():
            print(f"  {f:<11} <- {c['name']}  {c.get('type', '')}")
        missing = [f for f in issue.COLS if f not in cols]
        if missing:
            print("  not found (optional):", ", ".join(missing))
        if "DIV_CODE" in cols:
            r = datadb.run_select(f"SELECT `{cols['DIV_CODE']['name']}`, COUNT(*) FROM `{VIEW}` GROUP BY 1 ORDER BY 2 DESC", ["*"], max_rows=20)
            print("\n  DIV_CODE values -> division:", [(v, n, issue.div_of(v) or "?") for v, n in r["rows"]])
        pl = issue.plants_list(["*"])
        print(f"\n  {len(pl)} plants:")
        for x in pl:
            print(f"    {x['div'] or '?':<4} {x['plant']:<40} {x['lines']:,} lines")
    except Exception as e:
        print("  ERROR:", e)


if __name__ == "__main__":
    main()
