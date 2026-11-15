"""SO_DIAG.bat - what VIEW_SALES_ORDER_PBI has vs what the Sales Order MIS needs (column names only + totals)."""
from app import datadb
from app.engines import sales_order as so


def main():
    src = so.DEFAULT_SOURCE
    info = datadb.describe_tables([src], ["*"])[0]
    if info.get("error"):
        print("ERROR", info["error"]); return
    cols = [c["name"] for c in info["columns"]]
    print(f"{src}: {len(cols)} columns")
    for c in info["columns"]:
        print(f"  {c['name']:<34} {c.get('type', ''):<16} {c.get('comment') or ''}")
    norm = {so.norm(c): c for c in cols}
    print("\nMIS field -> view column")
    for k, al in so.A.items():
        hit = next((norm[a] for a in al if a in norm), None)
        print(f"  {k:<7} {'OK  ' + hit if hit else 'MISSING (looked for: ' + ', '.join(al) + ')'}")
    nums = [c["name"] for c in info["columns"] if any(t in str(c.get("type", "")).lower() for t in ("dec", "int", "double", "float", "num"))]
    if nums:
        sql = "SELECT COUNT(*) AS n_rows, " + ", ".join(f"ROUND(SUM(`{c}`),2) AS `{c}`" for c in nums[:25]) + f" FROM `{src}`"
        r = datadb.run_select(sql, ["*"], max_rows=5)
        print("\nTotals:", dict(zip(r["columns"], r["rows"][0])) if r.get("rows") else r)


    for c in ("DIVISION_CODE", "CLOSED_STATUS", "UNIT_OF_MEASURE", "RATE_UM", "QUOTATION_NO"):
        if c in cols:
            r = datadb.run_select(f"SELECT `{c}` AS v, COUNT(*) AS n FROM `{src}` GROUP BY `{c}` ORDER BY n DESC LIMIT 12", ["*"], max_rows=20)
            print(f"\n{c}:", [(row[0] if c != "QUOTATION_NO" else ("<blank>" if not row[0] else "<has value>"), row[1]) for row in r.get("rows", [])])


if __name__ == "__main__":
    main()
