"""Generates the MySQL queries for the Job Cardwise Scrap report.

Same logic as 'Job_Cardwise_Scrap__Generator.html' (aggregateSection / normProcess),
moved into SQL so the bot can run it on VIEW_JOB_CARD_SCRAP_PBI.

Placeholders filled per run:  {from_date} {to_date} {div}  (div = 1 for Kg, 1000 for MT)
Column placeholders (mapped once to the real view columns):
  {JOB} {PROCESS} {PLANT} {ITEM_GROUP} {PROD_DATE} {SCRAP} {PRODWS}
"""

VIEW = "VIEW_JOB_CARD_SCRAP_PBI"

SECTIONS = {
    "bb2bb": {
        "title": "Black Bar → Bright Bar",
        "procs": ["PEELING", "ROUND BAR CUTTING"],
        "buckets": [(10, "Above 10%"), (8, "8% - 10%"), (5, "5% - 8%"), (3, "3% - 5%"), (None, "Upto 3%")],
    },
    "bb2hollow": {
        "title": "Bright Bar → Hollow",
        "procs": ["PIERCING", "MOTHER HOLLOW CUTTING", "FINAL INSPECTION"],
        "exclude_ba_on": "FINAL INSPECTION",
        "item_group": "MOTHERHOLLOW",
        "buckets": [(10, "Above 10%"), (5, "5% - 10%"), (3, "3% - 5%"), (None, "Upto 3%")],
    },
    "cutting": {
        "title": "Hollow → Seamless",
        "procs": ["PILGER", "SINKING", "FINAL CUTTING & DEBURRING"],
        "plants": ["BA", "SEAMLESSPIPE1", "SEAMLESSPIPE2", "SEAMLESSTUBE"],
        "buckets": [(20, "Above 20%"), (15, "15% - 20%"), (10, "10% - 15%"), (5, "5% - 10%"),
                    (3, "3% - 5%"), (None, "Upto 3%")],
    },
}

PLANT_KEY = "REPLACE(REPLACE(REPLACE(UPPER({x}),' ',''),'-',''),CHAR(9),'')"

BASE = """WITH src AS (
  SELECT TRIM({JOB}) AS job,
         TRIM(REGEXP_REPLACE(COALESCE({PLANT},''), '[[:space:]]+', ' ')) AS plant,
         UPPER(TRIM(REGEXP_REPLACE(REPLACE(
             CASE WHEN LOCATE('-', {PROCESS}) > 0 THEN SUBSTRING({PROCESS}, LOCATE('-', {PROCESS}) + 1)
                  ELSE {PROCESS} END, '-', ' '), '[[:space:]]+', ' '))) AS p0,
         UPPER(REPLACE(COALESCE({ITEM_GROUP},''), ' ', '')) AS ig,
         COALESCE({SCRAP}, 0) AS scrap,
         COALESCE({PRODWS}, 0) AS prodws
  FROM VIEW_JOB_CARD_SCRAP_PBI
  WHERE {PROD_DATE} >= '{from_date}' AND {PROD_DATE} < DATE_ADD('{to_date}', INTERVAL 1 DAY)
    AND {JOB} IS NOT NULL AND TRIM({JOB}) <> ''
    AND UPPER({PROCESS}) NOT LIKE '%MACHINING%'
),
n1 AS (SELECT job, plant, ig, scrap, prodws, REPLACE(p0, ' AND ', ' & ') AS p0 FROM src),
norm AS (
  SELECT job, plant, ig, scrap, prodws,
    CASE
      WHEN p0 IN ('MH CUTTING','M H CUTTING','MOTHER HOLLOW CUTTING') OR p0 LIKE '%MH CUTTING%' THEN 'MOTHER HOLLOW CUTTING'
      WHEN p0 IN ('RB CUTTING','R B CUTTING','ROUND CUTTING','ROUND BAR CUTTING') THEN 'ROUND BAR CUTTING'
      WHEN p0 IN ('PILGERING','PILGER','COLD PILGER','COLD PILGERING') THEN 'PILGER'
      WHEN p0 LIKE '%CUTTING%' AND p0 LIKE '%DEBURR%' THEN 'FINAL CUTTING & DEBURRING'
      WHEN p0 LIKE '%FINAL INSPECTION' THEN 'FINAL INSPECTION'
      WHEN p0 LIKE 'PEEL%' THEN 'PEELING'
      WHEN p0 LIKE 'PIERC%' THEN 'PIERCING'
      WHEN p0 IN ('SINK','SINKING','SINKING MILL') THEN 'SINKING'
      ELSE p0 END AS proc
  FROM n1
)"""


def section_ctes(key: str, x: str = "") -> str:
    """x = name prefix so several sections can share one statement."""
    s = SECTIONS[key]
    procs = ", ".join(f"'{p}'" for p in s["procs"])
    where = [f"proc IN ({procs})"]
    if s.get("exclude_ba_on"):
        where.append(f"NOT (proc = '{s['exclude_ba_on']}' AND {PLANT_KEY.format(x='plant')} = 'BA')")
    if s.get("plants"):
        where.append(f"{PLANT_KEY.format(x='plant')} IN ({', '.join(repr(p) for p in s['plants'])})")
    ctes = [f"{x}sec0 AS (SELECT * FROM norm WHERE {' AND '.join(where)})"]
    if s.get("item_group"):
        # keep job cards with at least one row of the item group (blank item group also matches)
        ctes.append(f"{x}sec AS (SELECT * FROM {x}sec0 WHERE job IN (SELECT job FROM {x}sec0 WHERE ig = '' "
                    f"OR ig LIKE '%{s['item_group']}%'))")
    else:
        ctes.append(f"{x}sec AS (SELECT * FROM {x}sec0)")
    ctes.append(f"""{x}jp AS (SELECT job, COUNT(DISTINCT CASE WHEN plant = '' THEN '—' ELSE plant END) AS np FROM {x}sec GROUP BY job)""")
    ctes.append(f"""{x}keyed AS (
  SELECT s.*, CASE WHEN {x}jp.np > 1 THEN CONCAT(s.job, '||', s.plant) ELSE s.job END AS k
  FROM {x}sec s JOIN {x}jp ON {x}jp.job = s.job)""")
    ctes.append(f"""{x}perproc AS (SELECT k, job, proc, SUM(scrap) AS s, SUM(prodws) AS p FROM {x}keyed GROUP BY k, job, proc)""")
    ctes.append(f"""{x}rep AS (SELECT k, plant FROM (SELECT k, CASE WHEN plant = '' THEN '—' ELSE plant END AS plant,
  ROW_NUMBER() OVER (PARTITION BY k ORDER BY prodws DESC, plant) AS rn FROM {x}keyed) t WHERE rn = 1)""")
    case = "\n".join(f"      WHEN pct >= {lo} THEN '{label}'" for lo, label in s["buckets"] if lo is not None)
    last = s["buckets"][-1][1]
    order = "\n".join(f"      WHEN '{label}' THEN {i}" for i, (_, label) in enumerate(s["buckets"], 1))
    proc_cols = ",\n         ".join(
        f"SUM(CASE WHEN proc = '{p}' THEN s END) AS `{p} scrap`, SUM(CASE WHEN proc = '{p}' THEN p END) AS `{p} prod`"
        for p in s["procs"])
    ctes.append(f"""{x}jobs AS (
  SELECT j.*, CASE
{case}
      ELSE '{last}' END AS bucket
  FROM (SELECT pp.k, MIN(pp.job) AS job, MIN(r.plant) AS plant,
         SUM(pp.s) AS scrap, MAX(pp.p) AS prod,
         CASE WHEN MAX(pp.p) > 0 THEN SUM(pp.s) / MAX(pp.p) * 100 ELSE 0 END AS pct,
         {proc_cols}
        FROM {x}perproc pp JOIN {x}rep r ON r.k = pp.k GROUP BY pp.k) j
)""")
    ctes.append(f"""{x}bucket_order AS (SELECT b, CASE b
{order}
    END AS ord FROM (SELECT DISTINCT bucket AS b FROM {x}jobs
    UNION SELECT '{"' UNION SELECT '".join(l for _, l in s["buckets"])}') x)""")
    return ",\n".join(ctes)


def queries(key: str) -> dict[str, str]:
    s = SECTIONS[key]
    pre = BASE + ",\n" + section_ctes(key) + "\n"
    q = {}
    q["buckets"] = pre + """SELECT bo.b AS `Bucket`, COUNT(j.k) AS `Job cards`,
       ROUND(COALESCE(SUM(j.scrap),0)/{div}, 2) AS `Scrap Qty`,
       ROUND(COALESCE(SUM(j.prod),0)/{div}, 2) AS `Prod Qty w/ Scrap`,
       ROUND(CASE WHEN SUM(j.prod) > 0 THEN SUM(j.scrap)/SUM(j.prod)*100 ELSE 0 END, 2) AS `Scrap %`
FROM bucket_order bo LEFT JOIN jobs j ON j.bucket = bo.b
GROUP BY bo.b, bo.ord ORDER BY bo.ord"""
    q["plants"] = pre + """SELECT plant AS `Plant`, COUNT(*) AS `Job cards`,
       ROUND(SUM(scrap)/{div}, 2) AS `Scrap Qty`, ROUND(SUM(prod)/{div}, 2) AS `Prod Qty w/ Scrap`,
       ROUND(CASE WHEN SUM(prod) > 0 THEN SUM(scrap)/SUM(prod)*100 ELSE 0 END, 2) AS `Scrap %`
FROM jobs GROUP BY plant ORDER BY SUM(scrap) DESC"""
    q["jobs"] = pre + """SELECT bucket AS `Bucket`, job AS `Job Card No`, plant AS `Plant`,
       ROUND(scrap/{div}, 2) AS `Total Scrap`, ROUND(prod/{div}, 2) AS `Max Prod w/ Scrap`, ROUND(pct, 2) AS `Scrap %`
FROM jobs JOIN bucket_order bo ON bo.b = jobs.bucket
ORDER BY bo.ord, pct DESC, job, plant"""
    cols = ",\n       ".join(
        f"ROUND(COALESCE(`{p} scrap`,0)/{{div}}, 2) AS `{p.title()} Scrap`, "
        f"ROUND(COALESCE(`{p} prod`,0)/{{div}}, 2) AS `{p.title()} Prod`, "
        f"ROUND(CASE WHEN `{p} prod` > 0 THEN `{p} scrap`/`{p} prod`*100 ELSE 0 END, 2) AS `{p.title()} %`"
        for p in s["procs"])
    q["detail"] = pre + f"""SELECT job AS `Job Card No`, plant AS `Plant`,
       {cols},
       ROUND(scrap/{{div}}, 2) AS `Total Scrap`, ROUND(prod/{{div}}, 2) AS `Max Prod w/ Scrap`,
       ROUND(pct, 2) AS `Scrap %`, bucket AS `Bucket`
FROM jobs ORDER BY pct DESC, job, plant"""
    return q


def overall_plant_query() -> str:
    """Plant-wise summary across all three sections."""
    ctes = [section_ctes(k, f"{k}_") for k in SECTIONS]
    union = "\nUNION ALL\n".join(f"SELECT '{k}' AS sec, job, plant, scrap, prod FROM {k}_jobs" for k in SECTIONS)
    sums = ",\n       ".join(
        f"ROUND(SUM(CASE WHEN sec = '{k}' THEN scrap ELSE 0 END)/{{div}}, 2) AS `{v['title']} Scrap`, "
        f"ROUND(SUM(CASE WHEN sec = '{k}' THEN prod ELSE 0 END)/{{div}}, 2) AS `{v['title']} Prod`"
        for k, v in SECTIONS.items())
    return BASE + ",\n" + ",\n".join(ctes) + f""",
alljobs AS ({union})
SELECT plant AS `Plant`, COUNT(DISTINCT job) AS `Job cards`,
       {sums},
       ROUND(SUM(scrap)/{{div}}, 2) AS `Total Scrap`, ROUND(SUM(prod)/{{div}}, 2) AS `Total Prod`,
       ROUND(CASE WHEN SUM(prod) > 0 THEN SUM(scrap)/SUM(prod)*100 ELSE 0 END, 2) AS `Scrap %`
FROM alljobs GROUP BY plant ORDER BY SUM(scrap) DESC"""


def kpi_query() -> str:
    """Overall KPI cards: job cards in view (all processes except machining) + totals of the 3 sections."""
    ctes = [section_ctes(k, f"{k}_") for k in SECTIONS]
    union = "\nUNION ALL\n".join(f"SELECT scrap, prod FROM {k}_jobs" for k in SECTIONS)
    return BASE + ",\n" + ",\n".join(ctes) + f""",
alljobs AS ({union})
SELECT (SELECT COUNT(DISTINCT job) FROM norm) AS `Job cards in view`,
       ROUND(SUM(prod)/{{div}}, 2) AS `Production qty`,
       ROUND(SUM(scrap)/{{div}}, 2) AS `Scrap qty`,
       ROUND(CASE WHEN SUM(prod) > 0 THEN SUM(scrap)/SUM(prod)*100 ELSE 0 END, 2) AS `Overall scrap %`
FROM alljobs"""


def fill(sql: str, cols: dict, **params) -> str:
    out = sql
    for k, v in cols.items():
        out = out.replace("{" + k + "}", v)
    for k, v in params.items():
        out = out.replace("{" + k + "}", str(v))
    return out


def all_queries() -> dict[str, str]:
    out = {"kpis": kpi_query(), "overall_plants": overall_plant_query()}
    for k in SECTIONS:
        for name, q in queries(k).items():
            out[f"{k}_{name}"] = q
    return out


if __name__ == "__main__":
    import json
    print(json.dumps({k: list(queries(k)) for k in SECTIONS}))
