"""DISPATCH_CHECK.bat - load the Monthwise Sales Dispatch report and show how VIEW_SALE_INVOICE_PBI maps to it."""
import datetime as dt
import json
from pathlib import Path

from app import datadb, store
from app.engines import sale_dispatch as sd


def main():
    store.init_db()
    p = Path(__file__).resolve().parent.parent / "examples" / "skills" / "sales_dispatch_dashboard.json"
    s = store.save_skill(json.loads(p.read_text(encoding="utf-8")), changed_by="seed")
    print("report skill loaded:", s["name"], "| roles:", s.get("allowed_roles"))
    info = datadb.describe_tables([sd.DEFAULT_SOURCE], ["*"])[0]
    if info.get("error"):
        print("ERROR:", sd.DEFAULT_SOURCE, info["error"]); return
    H = [c["name"] for c in info["columns"]]
    print(f"\n{sd.DEFAULT_SOURCE}: {len(H)} columns")
    print("  " + ", ".join(H))
    C = sd.columns(H)
    print("\nDashboard field -> view column")
    for k, v in C.items():
        print(f"  {k:<6} {H[v] if v >= 0 else '-- not found --'}")
    t = dt.date.today()
    fy = sd.fy_start(t)
    try:
        out = sd.run(s, fy.isoformat(), t.isoformat(), ["*"])
        print("\nFY to date:", [(k["label"], k["value"], k.get("unit", "")) for k in out["kpis"]])
        for r in out["results"]["sd_month"]["rows"]:
            print("  ", r)
        print("checks:", out["checks"])
    except Exception as e:
        print("\nRUN ERROR:", e)


if __name__ == "__main__":
    main()
