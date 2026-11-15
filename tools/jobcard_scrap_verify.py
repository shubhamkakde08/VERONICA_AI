"""Cross-check: SQL results (MariaDB) vs a line-by-line Python port of the HTML tool's JavaScript."""
import math
import random
from datetime import date, timedelta

import mysql.connector

import jobcard_scrap_sql as B

COLS = dict(JOB="JOB_CARD_NO", PROCESS="PROCESS_NAME", PLANT="PLANT_NAME", ITEM_GROUP="ITEM_GROUP",
            PROD_DATE="PROD_DATE", SCRAP="SCRAP_QTY", PRODWS="PROD_QTY_WITH_SCRAP")

# ------------------------------------------------------------------ fake data (Oracle-style codes)
rnd = random.Random(42)
PROC_RAW = ["PEELI - PEELING", "ROUND - RB CUTTING", "PIERC - PIERCING", "MOTHE - MH CUTTING",
            "FINSP - FINAL INSPECTION", "PILGE - PILGERING", "SINKI - SINKING", "CUTTI - CUTTING & DEBURRING",
            "MACHI - MACHINING WO", "BRIGH - BRIGHT ANNEALING", "CUTTI - CUTTING AND DEBURRING"]
PLANTS = ["BA", "SEAMLESS PIPE- 1", "SEAMLESS PIPE- 2", "SEAMLESS TUBE", "BRIGHT BAR", "PIERCING PLANT"]
IGS = ["MOTHER HOLLOW", "FG SEAMLESS", "BRIGHT ROUND BAR", ""]
rows = []
used = set()
for j in range(1, 900):
    job = f"JC{j:05d}"
    home = rnd.choice(PLANTS)
    for _ in range(rnd.randint(1, 6)):
        pr = rnd.choice(PROC_RAW)
        plant = home if rnd.random() < 0.85 else rnd.choice(PLANTS)
        while True:   # unique prod values -> no ties in "plant of the biggest row"
            pws = round(rnd.uniform(50, 5000), 3)
            if pws not in used:
                used.add(pws)
                break
        scrap = round(pws * rnd.choice([0.005, 0.02, 0.04, 0.06, 0.09, 0.12, 0.17, 0.25]) * rnd.uniform(0.6, 1.2), 3)
        d = date(2026, 4, 1) + timedelta(days=rnd.randint(0, 200))
        rows.append((job, pr, plant, rnd.choice(IGS), d, scrap, pws))

def _db():
    """Credentials come from .env (DATA_DB_URL), never from this file."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from sqlalchemy.engine import make_url
    from app import config
    u = make_url(config.DATA_DB_URL)
    return mysql.connector.connect(host=u.host or "127.0.0.1", port=u.port or 3306, user=u.username,
                                   password=u.password, database=u.database)


con = _db()
cur = con.cursor()
cur.execute("DROP TABLE IF EXISTS VIEW_JOB_CARD_SCRAP_PBI")
cur.execute("""CREATE TABLE VIEW_JOB_CARD_SCRAP_PBI (JOB_CARD_NO TEXT, PROCESS_NAME TEXT, PLANT_NAME TEXT,
  ITEM_GROUP TEXT, PROD_DATE DATETIME, SCRAP_QTY DECIMAL(24,6), PROD_QTY_WITH_SCRAP DECIMAL(24,6))""")
cur.executemany("INSERT INTO VIEW_JOB_CARD_SCRAP_PBI VALUES (%s,%s,%s,%s,%s,%s,%s)", rows)
con.commit()

FROM, TO = date(2026, 4, 1), date(2026, 10, 12)


# ------------------------------------------------------------------ JS port
def norm_process(p):
    p = str(p or "").strip()
    parts = [s.strip() for s in p.split("-") if s.strip()]
    n = " ".join((" ".join(parts[1:]) if len(parts) > 1 else p).split()).upper()
    n = n.replace(" AND ", " & ")
    if n in ("MH CUTTING", "M H CUTTING", "MOTHER HOLLOW CUTTING") or "MH CUTTING" in n: n = "MOTHER HOLLOW CUTTING"
    if n in ("RB CUTTING", "R B CUTTING", "ROUND CUTTING", "ROUND BAR CUTTING"): n = "ROUND BAR CUTTING"
    if n in ("PILGERING", "PILGER", "COLD PILGER", "COLD PILGERING"): n = "PILGER"
    if n in ("CUTTING & DEBURRING", "CUTTING AND DEBURRING") or ("CUTTING" in n and "DEBURR" in n): n = "FINAL CUTTING & DEBURRING"
    if n == "FINAL INSPECTION" or n.endswith("FINAL INSPECTION"): n = "FINAL INSPECTION"
    if n == "PEELING" or n.startswith("PEEL"): n = "PEELING"
    if n == "PIERCING" or n.startswith("PIERC"): n = "PIERCING"
    if n in ("SINK", "SINKING", "SINKING MILL"): n = "SINKING"
    return n


pk = lambda s: s.upper().replace(" ", "").replace("-", "")
R = [dict(job=j, process=norm_process(p), raw=p, plant=" ".join(pl.split()), ig=ig.replace(" ", "").upper(),
          date=d, scrap=s, prodWS=w) for j, p, pl, ig, d, s, w in rows
     if FROM <= d <= TO and "MACHINING" not in p.upper()]

JS_SECTIONS = {
    "bb2bb": dict(processes=["PEELING", "ROUND BAR CUTTING"], buckets=[(10, math.inf, "Above 10%"), (8, 10, "8% - 10%"), (5, 8, "5% - 8%"), (3, 5, "3% - 5%"), (-math.inf, 3, "Upto 3%")]),
    "bb2hollow": dict(processes=["PIERCING", "MOTHER HOLLOW CUTTING", "FINAL INSPECTION"], excl={"FINAL INSPECTION": ["BA"]},
                      igf=["MOTHER HOLLOW", "MOTHERHOLLOW"], buckets=[(10, math.inf, "Above 10%"), (5, 10, "5% - 10%"), (3, 5, "3% - 5%"), (-math.inf, 3, "Upto 3%")]),
    "cutting": dict(processes=["PILGER", "SINKING", "FINAL CUTTING & DEBURRING"],
                    plants=["BA", "SEAMLESS PIPE- 1", "SEAMLESS PIPE- 2", "SEAMLESS TUBE", "SEAMLESS PIPE-1", "SEAMLESS PIPE-2"],
                    buckets=[(20, math.inf, "Above 20%"), (15, 20, "15% - 20%"), (10, 15, "10% - 15%"), (5, 10, "5% - 10%"), (3, 5, "3% - 5%"), (-math.inf, 3, "Upto 3%")]),
}


def ig_match(r, fl):
    if not r["ig"]:
        return True
    return any(r["ig"] == f.replace(" ", "") or f.replace(" ", "") in r["ig"] or r["ig"] in f.replace(" ", "") for f in fl)


def js_aggregate(sec):
    rs = [r for r in R if r["process"] in sec["processes"]]
    if sec.get("excl"):
        rs = [r for r in rs if not (r["process"] in sec["excl"] and pk(r["plant"]) in {pk(x) for x in sec["excl"][r["process"]]})]
    if sec.get("igf") and any(r["ig"] for r in rs):
        jobs = {r["job"] for r in rs if ig_match(r, sec["igf"])}
        rs = [r for r in rs if r["job"] in jobs]
    if sec.get("plants"):
        ps = {pk(x) for x in sec["plants"]}
        rs = [r for r in rs if pk(r["plant"]) in ps]
    plants_of = {}
    for r in rs:
        plants_of.setdefault(r["job"], set()).add(r["plant"] or "—")
    by = {}
    for r in rs:
        key = (r["job"] + "||" + (r["plant"] or "—")) if len(plants_of[r["job"]]) > 1 else r["job"]
        g = by.setdefault(key, dict(job=r["job"], procs={}, rep=-1, plant=""))
        pr = g["procs"].setdefault(r["process"], dict(scrap=0, prod=0))
        pr["scrap"] += r["scrap"]
        pr["prod"] += r["prodWS"]
        if r["prodWS"] > g["rep"]:
            g["rep"], g["plant"] = r["prodWS"], r["plant"]
    jobs = []
    for g in by.values():
        ts = sum(v["scrap"] for v in g["procs"].values())
        mp = max(v["prod"] for v in g["procs"].values())
        pct = ts / mp * 100 if mp else 0
        b = next(lbl for lo, hi, lbl in sec["buckets"] if (lo <= pct < hi) or (hi == math.inf and pct >= lo))
        jobs.append(dict(job=g["job"], plant=g["plant"] or "—", scrap=ts, prod=mp, pct=pct, bucket=b))
    return jobs


# ------------------------------------------------------------------ compare
ok = True
for key, sec in JS_SECTIONS.items():
    js = js_aggregate(sec)
    q = B.queries(key)
    cur.execute(B.fill(q["buckets"], COLS, from_date=FROM, to_date=TO, div=1))
    sql_b = {r[0]: r[1:] for r in cur.fetchall()}
    print(f"\n== {B.SECTIONS[key]['title']}: {len(js)} job rows (JS)")
    for lo, hi, lbl in sec["buckets"]:
        jj = [j for j in js if j["bucket"] == lbl]
        js_row = (len(jj), round(sum(j["scrap"] for j in jj), 2), round(sum(j["prod"] for j in jj), 2))
        s = sql_b.get(lbl)
        sql_row = (s[0], float(s[1]), float(s[2])) if s else None
        match = sql_row is not None and sql_row[0] == js_row[0] and abs(sql_row[1] - js_row[1]) < 0.02 and abs(sql_row[2] - js_row[2]) < 0.02
        ok &= match
        print(f"  {lbl:<11} JS {js_row}  SQL {sql_row}  {'OK' if match else 'MISMATCH'}")
    cur.execute(B.fill(q["jobs"], COLS, from_date=FROM, to_date=TO, div=1))
    sql_jobs = {(r[1], r[2]): (float(r[3]), float(r[4]), float(r[5]), r[0]) for r in cur.fetchall()}
    js_jobs = {(j["job"], j["plant"]): (round(j["scrap"], 2), round(j["prod"], 2), round(j["pct"], 2), j["bucket"]) for j in js}
    diff = [k for k in js_jobs if k not in sql_jobs or any(abs(a - b) > 0.011 for a, b in zip(js_jobs[k][:3], sql_jobs[k][:3])) or js_jobs[k][3] != sql_jobs[k][3]]
    extra = [k for k in sql_jobs if k not in js_jobs]
    print(f"  job-level rows: JS {len(js_jobs)}  SQL {len(sql_jobs)}  differences {len(diff)}  extra {len(extra)}")
    ok &= not diff and not extra
    for k in (diff + extra)[:5]:
        print("   ", k, js_jobs.get(k), sql_jobs.get(k))
    for name in ("plants", "detail"):
        cur.execute(B.fill(q[name], COLS, from_date=FROM, to_date=TO, div=1000))
        cur.fetchall()

cur.execute(B.fill(B.overall_plant_query(), COLS, from_date=FROM, to_date=TO, div=1))
ov = cur.fetchall()
tot = sum(float(r[-3]) for r in ov)
js_tot = sum(round(sum(j["scrap"] for j in js_aggregate(s)), 6) for s in JS_SECTIONS.values())
print(f"\nOverall plant table: {len(ov)} plants, total scrap SQL {tot:.2f} vs JS {js_tot:.2f}")
ok &= abs(tot - js_tot) < 0.1
cur.execute(B.fill(B.kpi_query(), COLS, from_date=FROM, to_date=TO, div=1))
print("KPI:", cur.fetchone(), " JS jobs:", len({r['job'] for r in R}))
print("\nALL MATCH" if ok else "\nSOME MISMATCH")
