"""End-to-end test with a sample SQLite "ERP" and a scripted fake Claude.

Run:  python -m pytest -q tests/   (no API key or MySQL needed)
"""
import os
import random
import sqlite3
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

TMP = Path(tempfile.mkdtemp(prefix="rbtest_"))
os.environ.update(
    DATA_DB_URL=f"sqlite:///{TMP/'erp.db'}", BOT_DB_URL=f"sqlite:///{TMP/'bot.db'}",
    OUTPUT_DIR=str(TMP / "out"), SERVICE_API_KEY="svc", BOOTSTRAP_ADMIN_WEB_TOKEN="admintok",
    BOOTSTRAP_ADMIN_TELEGRAM_ID="111", TELEGRAM_BOT_TOKEN="", PUBLIC_BASE_URL="http://test",
    WEB_REQUIRE_PASSWORD="true",
)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def make_sample_erp(path: Path):
    con = sqlite3.connect(path)
    con.executescript("""
    CREATE TABLE branches(id INTEGER PRIMARY KEY, name TEXT);
    CREATE TABLE customers(id INTEGER PRIMARY KEY, name TEXT, city TEXT);
    CREATE TABLE invoices(id INTEGER PRIMARY KEY, invoice_no TEXT, invoice_date DATE,
        branch_id INTEGER REFERENCES branches(id), customer_id INTEGER REFERENCES customers(id),
        qty_mt REAL, amount REAL, status TEXT);
    CREATE TABLE salaries(id INTEGER PRIMARY KEY, emp TEXT, salary REAL);
    """)
    con.executemany("INSERT INTO branches VALUES(?,?)",
                    [(1, "Surat"), (2, "Ahmedabad"), (3, "Pune"), (4, "Indore")])
    con.executemany("INSERT INTO customers VALUES(?,?,?)",
                    [(i, f"Customer {i}", random.choice(["Surat", "Pune", "Delhi"])) for i in range(1, 21)])
    rnd = random.Random(7)
    rows, d0 = [], date.today() - timedelta(days=40)
    for i in range(1, 600):
        d = d0 + timedelta(days=rnd.randint(0, 40))
        rows.append((i, f"INV{i:05d}", d.isoformat(), rnd.randint(1, 4), rnd.randint(1, 20),
                     round(rnd.uniform(1, 25), 2), round(rnd.uniform(20000, 900000), 2),
                     "C" if rnd.random() < 0.08 else "A"))
    con.executemany("INSERT INTO invoices VALUES(?,?,?,?,?,?,?,?)", rows)
    con.execute("INSERT INTO salaries VALUES(1,'x',1)")
    con.commit()


make_sample_erp(TMP / "erp.db")

from app import agent, datadb, renderers, store  # noqa: E402

store.init_db()

SQL = """SELECT b.name AS Branch, COUNT(*) AS Invoices, ROUND(SUM(i.qty_mt),2) AS "Qty (MT)",
 ROUND(SUM(i.amount),2) AS "Amount" FROM invoices i JOIN branches b ON b.id=i.branch_id
 WHERE i.status <> 'C' GROUP BY b.name ORDER BY "Amount" DESC"""


# ------------------------------------------------------------- fake Claude
def tool_use(name, inp, i):
    return SimpleNamespace(type="tool_use", id=f"tu{i}", name=name, input=inp)


def text(t):
    return SimpleNamespace(type="text", text=t)


class FakeClaude:
    """Replays a script of responses; records what the agent sent back."""
    def __init__(self, script):
        self.script, self.calls = list(script), []
        self.messages = self

    def create(self, **kw):
        self.calls.append({**kw, "messages": list(kw["messages"])})
        content, stop = self.script.pop(0)
        return SimpleNamespace(content=content, stop_reason=stop)


def admin():
    return store.get_user_by_token("admintok")


# ------------------------------------------------------------- tests
def test_sql_guard():
    for bad in ["DELETE FROM invoices", "SELECT 1; DROP TABLE invoices",
                "UPDATE invoices SET amount=0", "SELECT * FROM invoices INTO OUTFILE '/tmp/x'"]:
        try:
            datadb.validate_select(bad, ["*"])
            raise AssertionError(f"not rejected: {bad}")
        except datadb.SQLRejected:
            pass
    datadb.validate_select("WITH x AS (SELECT * FROM invoices) SELECT * FROM x", ["invoices"])
    try:
        datadb.validate_select("SELECT * FROM salaries", ["invoices", "branches"])
        raise AssertionError("role table restriction failed")
    except datadb.SQLRejected:
        pass


def test_indian_numbers():
    assert renderers.indian_group(12345678.5) == "1,23,45,678.50"
    assert renderers.indian_group(999, 0) == "999"
    assert renderers.indian_group(-100000, 0) == "-1,00,000"


def test_teach_then_run_with_all_formats():
    # 1) Teaching: agent explores, tests SQL, saves the skill
    agent.client = FakeClaude([
        ([tool_use("list_tables", {"search": ""}, 1)], "tool_use"),
        ([tool_use("describe_tables", {"tables": ["invoices", "branches"]}, 2)], "tool_use"),
        ([tool_use("run_sql", {"sql": SQL}, 3)], "tool_use"),
        ([tool_use("save_report_skill", {
            "name": "branch_sales", "title": "Branch-wise Sales",
            "rules": "1. Exclude cancelled (status='C')\n2. Amount without GST",
            "output_format": "Branch | Invoices | Qty (MT) | Amount, sort Amount desc, total row, bar chart",
            "default_formats": ["table", "excel", "pdf", "chart", "html"], "sql_template": SQL}, 4)],
         "tool_use"),
        ([text("✅ Saved. Run it any time with /branch_sales")], "end_turn"),
    ])
    r = agent.handle_message(admin(), "/teach branch wise sales", "web", "web:t1")
    assert "branch_sales" in r.text
    tools_seen = [c for c in agent.client.calls[3]["messages"][-1]["content"]]
    assert '"row_count": 4' in tools_seen[0]["content"]
    assert store.get_skill("branch_sales")["version"] == 1

    # 2) Running the skill in Hindi -> all 5 formats
    agent.client = FakeClaude([
        ([tool_use("run_sql", {"sql": SQL}, 5)], "tool_use"),
        ([tool_use("create_report", {
            "result_id": "r1", "title": "शाखा अनुसार बिक्री", "subtitle": "पिछले 40 दिन",
            "summary": "कुल बिक्री में सूरत सबसे आगे है।\nरद्द इनवॉइस शामिल नहीं हैं।",
            "formats": ["table", "excel", "pdf", "chart", "html"],
            "column_formats": {"Amount": "currency", "Qty (MT)": "number"},
            "total_columns": ["Invoices", "Qty (MT)", "Amount"],
            "chart": {"type": "bar", "x": "Branch", "y": ["Amount"]}}, 6)], "tool_use"),
        ([text("रिपोर्ट तैयार है।")], "end_turn"),
    ])
    r = agent.handle_message(admin(), "/branch_sales hindi me", "telegram", "tg:111")
    # the skill definition was injected into the first user message
    first_user = agent.client.calls[0]["messages"][-1]["content"]
    assert "<skill_definition>" in first_user and "Exclude cancelled" in first_user
    fmts = sorted(f["format"] for f in r.files)
    assert fmts == ["chart", "excel", "html", "pdf"], fmts
    assert r.tables and "TOTAL" in r.tables[0]
    for f in r.files:
        assert Path(f["path"]).stat().st_size > 1000
    # 3) History
    hist = store.search_reports(admin())
    assert hist and hist[0]["skill_name"] == "branch_sales"
    print("\nFILES:", *[f["path"] for f in r.files], sep="\n  ")
    print(r.tables[0])


def test_viewer_cannot_free_query_or_teach():
    v = store.add_user("Viewer", "viewer", telegram_id="222")
    agent.client = FakeClaude([
        ([tool_use("run_sql", {"sql": "SELECT * FROM invoices"}, 1),
          tool_use("save_report_skill", {"name": "x_y", "title": "t", "rules": "r",
                                         "output_format": "f"}, 2)], "tool_use"),
        ([text("Sorry")], "end_turn"),
    ])
    agent.handle_message(v, "show all invoices", "web", "web:v")
    results = agent.client.calls[1]["messages"][-1]["content"]
    assert "only run taught reports" in results[0]["content"]
    assert "not allowed to teach" in results[1]["content"]


def test_schedule_creation():
    from app import scheduler
    agent.client = FakeClaude([
        ([tool_use("create_schedule", {"skill_name": "branch_sales", "cron": "0 9 * * 1-6"}, 1)],
         "tool_use"),
        ([text("Har subah 9 baje bhej dunga.")], "end_turn"),
    ])
    a = admin()
    store.set_user_contact(a["id"], email="boss@venuspipes.com")       # Telegram is off -> schedules go by e-mail
    agent.handle_message(store.get_user(a["id"]), "roj subah 9 baje /branch_sales bhejo", "web", "web:1")
    s = store.list_schedules()
    assert s and s[0]["cron"] == "0 9 * * 1-6" and s[0]["target_chat_id"] == "email:boss@venuspipes.com"
    assert scheduler.next_run(s[0]["id"])


def _login(c, username, password):
    return c.post("/api/login", json={"username": username, "password": password})


def test_web_login_and_api():
    from fastapi.testclient import TestClient
    from app.main import app
    store.set_login(1, "admin", "AdminPass123")
    with TestClient(app) as c:
        assert c.get("/api/auth-mode").json()["password_required"] is True
        # old personal token links no longer work in password mode
        assert c.get("/api/me", headers={"Authorization": "Bearer admintok"}).status_code == 401
        assert _login(c, "admin", "wrong-pass").status_code == 401
        r = _login(c, "ADMIN", "AdminPass123")          # usernames are case-insensitive
        assert r.status_code == 200, r.text
        H = {"Authorization": "Bearer " + r.json()["token"]}
        me = c.get("/api/me", headers=H).json()
        assert me["role"] == "admin" and any(s["name"] == "branch_sales" for s in me["skills"])
        # password hash is never returned
        assert all("password_hash" not in u for u in c.get("/api/users", headers=H).json())
        # n8n teach-form path works with the API key only while the chat bridge is on
        from app import config
        config.TELEGRAM_ENABLED = True
        r = c.post("/api/skills", headers={"X-API-Key": "svc", "X-Telegram-Id": "111"},
                   json={"name": "Daily Dispatch", "title": "Daily Dispatch", "rules": "1. x",
                         "output_format": "y", "default_formats": ["excel"]})
        assert r.json()["command"] == "/daily_dispatch", r.text
        config.TELEGRAM_ENABLED = False
        h = c.get("/api/history", headers=H).json()
        assert c.get(h[0]["files"][0]["url"].replace("http://test", "")).status_code == 200
        # change password -> old session ends, new password works
        assert c.post("/api/change-password", headers=H,
                      json={"old_password": "AdminPass123", "new_password": "NewPass4567"}).status_code == 200
        assert c.get("/api/me", headers=H).status_code == 401
        r = _login(c, "admin", "NewPass4567")
        H = {"Authorization": "Bearer " + r.json()["token"]}
        assert c.post("/api/logout", headers=H).status_code == 200
        assert c.get("/api/me", headers=H).status_code == 401
        assert "Sign in" in c.get("/").text


def test_lockout_and_disable():
    from fastapi.testclient import TestClient
    from app.main import app, _fails
    _fails.clear()
    u = store.add_user("Lock Test", "viewer")
    store.set_login(u["id"], "locktest", "RightPass99")
    with TestClient(app) as c:
        for _ in range(5):
            assert _login(c, "locktest", "nope").status_code == 401
        assert _login(c, "locktest", "RightPass99").status_code == 429   # locked even with right pw
        _fails.clear()
        tok = _login(c, "locktest", "RightPass99").json()["token"]
        store.set_active(u["id"], False)                                  # disable -> session dead
        assert c.get("/api/me", headers={"Authorization": "Bearer " + tok}).status_code == 401
        assert _login(c, "locktest", "RightPass99").status_code == 401
    _fails.clear()


def test_password_rules_and_upgrade():
    import pytest
    with pytest.raises(ValueError):
        store.set_login(1, "ab", "longenough1")          # username too short
    with pytest.raises(ValueError):
        store.set_login(1, "admin", "short")             # password too short
    h = store.hash_password("Secret123")
    assert h.startswith("pbkdf2_sha256$") and "Secret123" not in h
    assert store.check_password("Secret123", h) and not store.check_password("secret123", h)
    # an install from before this update (no username/password columns) is upgraded in place
    import sqlalchemy as sa
    e = sa.create_engine(f"sqlite:///{TMP/'old.db'}")
    with e.begin() as c:
        c.execute(sa.text("CREATE TABLE rb_users (id INTEGER PRIMARY KEY, name TEXT, role TEXT, "
                          "telegram_id TEXT, web_token TEXT, active BOOLEAN, created_at DATETIME)"))
    old_engine = store.engine
    store.engine = e
    try:
        store._upgrade_existing_tables()
        cols = {c["name"] for c in sa.inspect(e).get_columns("rb_users")}
        assert {"username", "password_hash"} <= cols
        store._upgrade_existing_tables()                 # running twice is harmless
    finally:
        store.engine = old_engine


# ------------------------------------------------------------- seamless production pack
def _make_tubing_view():
    import sqlite3
    rnd = random.Random(11)
    con = sqlite3.connect(TMP / "erp.db")
    con.execute("""CREATE TABLE IF NOT EXISTS VIEW_TUBING_PBI (vr_date DATE, plant_code TEXT, item_group TEXT,
        final_grade TEXT, job_card_type TEXT, process_name TEXT, machine_name TEXT, job_card_no TEXT,
        prod_qty REAL, prod_scrap_qty REAL, scrap_qty REAL)""")
    plan = {"BA": ["FG Seamless"], "SMLST": ["FG Seamless"], "SMLP2": ["Bright Round Bar", "FG Seamless", "Mother Hollow"],
            "SMLSP": ["Bright Round Bar", "FG Seamless", "Mother Hollow"]}
    procs = {"FG Seamless": ["Drawing", "Sinking", "Bright Annealing", "Degreasing", "Cutting & Deburring", "Passivation"],
             "Bright Round Bar": ["Peeling"], "Mother Hollow": ["Inter Picklle", "Mh Cutting", "Solution Annealing"]}
    rows, n = [], 0
    for m in range(4, 11):
        for plant, groups in plan.items():
            for g in groups:
                for pr in procs[g]:
                    for jt in ("FINAL", "INTER"):
                        n += 1
                        q = round(rnd.uniform(5, 60), 2)
                        s = round(q * rnd.uniform(0, 0.02), 2)
                        rows.append((f"2026-{m:02d}-{rnd.randint(1, 28):02d}", plant, g,
                                     rnd.choice(["304", "316", "316TI", "DUPLEX", "321"]), jt, pr, f"M{rnd.randint(1,6)}",
                                     f"JC{n:05d}", q, round(q + s, 2), s))
    con.executemany("INSERT INTO VIEW_TUBING_PBI VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    con.commit()
    datadb.refresh_schema_cache()


def test_seamless_production_pack():
    import json as _json
    _make_tubing_view()
    store.save_skill(_json.load(open(Path(__file__).resolve().parent.parent /
                                     "examples/skills/seamless_production.json")), changed_by="test")
    W = "WHERE vr_date BETWEEN '2026-04-01' AND '2026-10-12' AND plant_code IN ('BA','SMLST')"
    kpi = f"""SELECT ROUND(SUM(prod_qty),2) AS `Production Qty`, ROUND(SUM(prod_scrap_qty),2) AS `Production + Scrap Qty`,
        ROUND(SUM(scrap_qty),2) AS `Total Scrap`, COUNT(DISTINCT job_card_no) AS `Job Card Count`,
        ROUND(SUM(scrap_qty)/SUM(prod_scrap_qty)*100,2) AS `Scrap %` FROM VIEW_TUBING_PBI {W}"""
    grade = f"SELECT final_grade AS `Final Grade`, ROUND(SUM(prod_scrap_qty),2) AS `Production + Scrap Qty` FROM VIEW_TUBING_PBI {W} GROUP BY 1 ORDER BY 2 DESC"
    month = f"""SELECT strftime('%m', vr_date) AS `Month`, ROUND(SUM(scrap_qty),2) AS `Scrap Qty`, ROUND(SUM(prod_scrap_qty),2) AS `Gross Qty`,
        ROUND(SUM(scrap_qty)/SUM(prod_scrap_qty)*100,2) AS `Scrap %` FROM VIEW_TUBING_PBI {W} GROUP BY 1 ORDER BY 1"""
    jc = f"""SELECT plant_code AS `Plant Code`, item_group AS `Item Group`, process_name AS `Process`,
        ROUND(SUM(CASE WHEN job_card_type='FINAL' THEN prod_qty END),2) AS `FINAL`,
        ROUND(SUM(CASE WHEN job_card_type='INTER' THEN prod_qty END),2) AS `INTER`, ROUND(SUM(prod_qty),2) AS `Total`
        FROM VIEW_TUBING_PBI {W} GROUP BY 1,2,3 ORDER BY 1,2,6"""
    sc = f"""SELECT plant_code AS `Plant Code`, item_group AS `Item Group`, process_name AS `Process`,
        ROUND(SUM(CASE WHEN job_card_type='FINAL' THEN scrap_qty END)/SUM(CASE WHEN job_card_type='FINAL' THEN prod_scrap_qty END)*100,2) AS `FINAL`,
        ROUND(SUM(CASE WHEN job_card_type='INTER' THEN scrap_qty END)/SUM(CASE WHEN job_card_type='INTER' THEN prod_scrap_qty END)*100,2) AS `INTER`,
        ROUND(SUM(scrap_qty)/SUM(prod_scrap_qty)*100,2) AS `Total`,
        SUM(CASE WHEN job_card_type='FINAL' THEN scrap_qty END) AS `Scrap FINAL`, SUM(CASE WHEN job_card_type='FINAL' THEN prod_scrap_qty END) AS `Gross FINAL`,
        SUM(CASE WHEN job_card_type='INTER' THEN scrap_qty END) AS `Scrap INTER`, SUM(CASE WHEN job_card_type='INTER' THEN prod_scrap_qty END) AS `Gross INTER`,
        SUM(scrap_qty) AS `Scrap Total`, SUM(prod_scrap_qty) AS `Gross Total`
        FROM VIEW_TUBING_PBI {W} GROUP BY 1,2,3 ORDER BY 1,2,3"""
    sql_calls = [tool_use("run_sql", {"sql": q}, i) for i, q in enumerate([kpi, grade, month, jc, sc], 1)]
    agent.client = FakeClaude([(sql_calls, "tool_use"), ([], "pending")])
    # second response needs KPI values from the first result -> build it after a dry run
    ctx_kpi = datadb.run_select(kpi, ["*"])["rows"][0]
    k = dict(zip(["Production Qty", "Production + Scrap Qty", "Total Scrap", "Job Card Count", "Scrap %"], ctx_kpi))
    helpers = ["Scrap FINAL", "Gross FINAL", "Scrap INTER", "Gross INTER", "Scrap Total", "Gross Total"]
    agent.client = FakeClaude([
        (sql_calls, "tool_use"),
        ([tool_use("create_report_pack", {
            "title": "Seamless Pipe / Tube / BA Production Details",
            "filters": {"Vr Date": "01-04-2026 to 12-10-2026", "Plant group": "BA (BA, SMLST)"},
            "kpis": [{"label": "Production Qty", "value": k["Production Qty"]},
                     {"label": "Production + Scrap Qty", "value": k["Production + Scrap Qty"]},
                     {"label": "Total Scrap", "value": k["Total Scrap"]},
                     {"label": "Job Card Count", "value": k["Job Card Count"]},
                     {"label": "Scrap %", "value": k["Scrap %"], "format": "percent"}],
            "summary": "BA group: scrap 0.9% overall. ✅ Checks passed",
            "sections": [
                {"result_id": "r2", "title": "BA - Production Qty with Scrap by Final Grade",
                 "chart": {"type": "barh", "x": "Final Grade", "y": ["Production + Scrap Qty"]}},
                {"result_id": "r3", "title": "BA - Scrap % by Month", "hidden_columns": ["Scrap Qty", "Gross Qty"],
                 "ratio_columns": {"Scrap %": ["Scrap Qty", "Gross Qty", 100]},
                 "column_formats": {"Scrap %": "percent"},
                 "chart": {"type": "line", "x": "Month", "y": ["Scrap %"]}},
                {"result_id": "r4", "title": "BA - Job Cardwise Prod Qty", "group_by": ["Plant Code", "Item Group"],
                 "total_columns": ["FINAL", "INTER", "Total"]},
                {"result_id": "r5", "title": "BA - Plant-Job Cardwise Scrap %", "group_by": ["Plant Code", "Item Group"],
                 "hidden_columns": helpers, "column_formats": {"FINAL": "percent", "INTER": "percent", "Total": "percent"},
                 "ratio_columns": {"FINAL": ["Scrap FINAL", "Gross FINAL", 100], "INTER": ["Scrap INTER", "Gross INTER", 100],
                                   "Total": ["Scrap Total", "Gross Total", 100]}},
            ],
            "formats": ["table", "chart", "pdf", "excel", "html"]}, 9)], "tool_use"),
        ([text("BA report ready.")], "end_turn"),
    ])
    r = agent.handle_message(admin(), "/seamless_production BA", "telegram", "tg:111")
    first = agent.client.calls[0]["messages"][-1]["content"]
    assert "VIEW_TUBING_PBI" in first and "SMLST" in first          # skill injected
    res = agent.client.calls[2]["messages"][-1]["content"][0]["content"]
    assert '"report_id"' in res, res
    assert sorted({f["format"] for f in r.files}) == ["chart", "excel", "html", "pdf"]
    assert len([f for f in r.files if f["format"] == "chart"]) == 2
    assert r.kpis[0]["label"] == "Production Qty"
    assert r.tables[0].startswith("Seamless Pipe") and "Job Card Count" in r.tables[0]
    jc_table = next(t for t in r.tables if "Job Cardwise Prod Qty" in t)
    assert "▸ BA" in jc_table and "▸ FG Seamless" in jc_table and "TOTAL" in jc_table
    # grand total of section E equals KPI production qty (cross-check 1)
    tot_line = [l for l in jc_table.splitlines() if l.startswith("TOTAL")][0]
    assert renderers.indian_group(k["Production Qty"]) in tot_line, (tot_line, k)
    # scrap % total recomputed as a ratio, equals KPI scrap %
    sc_table = next(t for t in r.tables if "Scrap %" in t and "Plant-Job" in t)
    assert f"{k['Scrap %']:.2f}%" in [l for l in sc_table.splitlines() if l.startswith("TOTAL")][0]
    print("\n" + "\n\n".join(r.tables[:1] + [jc_table]))
    print("FILES:", *[f["path"] for f in r.files], sep="\n  ")


def test_new_tables_appear_without_restart():
    import sqlite3
    datadb.list_tables(["*"])                                   # fill the cache
    con = sqlite3.connect(TMP / "erp.db")
    con.execute("CREATE TABLE VIEW_NEW_SYNC_PBI (a INTEGER)")
    con.execute("CREATE TABLE VIEW_NEW_SYNC_PBI__new (a INTEGER)")   # sync temp copy: hidden
    con.commit()
    assert "VIEW_NEW_SYNC_PBI" in [d["table"] for d in datadb.describe_tables(["VIEW_NEW_SYNC_PBI"], ["*"])
                                   if "error" not in d]
    assert "VIEW_NEW_SYNC_PBI__new" not in datadb.list_tables(["*"])
    datadb.run_select("SELECT COUNT(*) FROM VIEW_NEW_SYNC_PBI", ["*"])


def test_run_skill_query_tool_is_safe():
    import json as _json
    stored = {"columns": {"QTY": "prod_qty", "DT": "vr_date"},
              "queries": {"total": "SELECT ROUND(SUM({QTY})/{div},2) AS q FROM VIEW_TUBING_PBI "
                                   "WHERE {DT} BETWEEN '{from_date}' AND '{to_date}'"}}
    store.save_skill({"name": "stored_demo", "title": "Stored demo", "rules": "r", "output_format": "f",
                      "sql_template": _json.dumps(stored)}, changed_by="t")
    ctx = agent.Ctx(user=admin(), role=store.get_role("admin"), channel="web", chat_key="x", request_text="")
    ok = agent._tool_run_skill_query(ctx, "stored_demo", "total", "2026-04-01", "2026-12-31", "mt")
    assert "result_id" in ok and ok["row_count"] == 1, ok
    bad = agent._tool_run_skill_query(ctx, "stored_demo", "total", "2026-04-01' OR '1'='1", "2026-12-31")
    assert "error" in bad                                     # injection via dates refused
    assert "error" in agent._tool_run_skill_query(ctx, "stored_demo", "nope", "2026-04-01", "2026-12-31")
    assert "error" in agent._tool_set_skill_columns(ctx, "stored_demo", {"QTY": "x; DROP TABLE y"})
    v = store.add_user("Viewer2", "viewer")
    vctx = agent.Ctx(user=v, role=store.get_role("viewer"), channel="web", chat_key="v", request_text="")
    assert "error" in agent._tool_set_skill_columns(vctx, "stored_demo", {"QTY": "prod_qty"})
    assert "result_id" in agent._tool_run_skill_query(vctx, "stored_demo", "total", "2026-04-01", "2026-12-31")
    view = agent._tool_get_report_skill(ctx, "stored_demo")
    assert view["stored_queries"] == ["total"] and view["sql_template"] is None   # SQL not shown to the AI


# ------------------------------------------------------------- voice (Gemini mocked)
def _mock_gemini(calls):
    import base64 as _b64
    import json as _json

    import httpx

    def handler(req):
        body = _json.loads(req.content)
        calls.append(body)
        if body["model"].endswith("tts"):
            fmt = body["response_format"]["mime_type"]
            data = b"OggS-fake" if "ogg" in fmt else b"ID3-fake-mp3"
            return httpx.Response(200, json={"id": "i1", "status": "completed", "steps": [
                {"type": "model_output", "content": [{"type": "audio", "data": _b64.b64encode(data).decode(), "mime_type": fmt}]}]})
        return httpx.Response(200, json={"id": "i2", "status": "completed", "steps": [
            {"type": "model_output", "content": [{"type": "text", "text": "aaj ka scrap kitna hai"}]}]})
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_voice_web_endpoints_and_cache():
    from fastapi.testclient import TestClient
    from app import config, voice
    from app.main import app
    config.GEMINI_API_KEY = "test-key"
    calls = []
    voice._http = _mock_gemini(calls)
    u = store.add_user("Voice User", "manager")
    store.set_login(u["id"], "voiceuser", "VoicePass123")
    with TestClient(app) as c:
        tok = c.post("/api/login", json={"username": "voiceuser", "password": "VoicePass123"}).json()["token"]
        H = {"Authorization": "Bearer " + tok}
        assert c.get("/api/me", headers=H).json()["voice"] is True
        r = c.post("/api/tts", headers=H, json={"text": "**Scrap 9.5%** aaj ✅", "lang": "hi-IN"})
        assert r.status_code == 200 and r.headers["content-type"] == "audio/mpeg" and r.content == b"ID3-fake-mp3"
        sent = calls[-1]
        assert sent["model"] == "gemini-3.8-flash-tts" and sent["generation_config"]["speech_config"][0]["language"] == "hi-IN"
        assert sent["input"][0]["content"][0]["text"] == "Scrap 9.5 percent aaj"          # markdown/emoji removed
        n = len(calls)
        c.post("/api/tts", headers=H, json={"text": "**Scrap 9.5%** aaj ✅", "lang": "hi-IN"})
        assert len(calls) == n                                                         # served from cache
        r = c.post("/api/stt", headers=H, files={"audio": ("v.webm", b"\x1aE\xdf\xa3fake", "audio/webm;codecs=opus")})
        assert r.json()["text"] == "aaj ka scrap kitna hai"
        assert calls[-1]["input"][0]["content"][1]["mime_type"] == "audio/webm"
        assert c.post("/api/tts", json={"text": "x"}).status_code == 401                # login needed
    config.GEMINI_API_KEY = ""


def test_telegram_voice_note_gets_voice_reply():
    from types import SimpleNamespace
    from app import config, telegram, voice
    config.GEMINI_API_KEY = "test-key"
    voice._http = _mock_gemini([])
    sent = []
    telegram._call = lambda method, **kw: sent.append((method, kw)) or {"ok": True, "result": {}}
    telegram._download = lambda fid: ("voice/file.oga", b"OggS-voice")
    agent.client = FakeClaude([([SimpleNamespace(type="text", text="Aaj ka scrap 9.5 percent hai.")], "end_turn")])
    telegram.process_update({"message": {"chat": {"id": 111, "type": "private"}, "from": {"id": 111},
                                         "voice": {"file_id": "abc", "mime_type": "audio/ogg", "duration": 3}}})
    methods = [m for m, _ in sent]
    assert "sendVoice" in methods, methods
    heard = [kw for m, kw in sent if m == "sendMessage" and "🎙️" in kw["json"]["text"]]
    assert heard and "aaj ka scrap kitna hai" in heard[0]["json"]["text"]
    config.GEMINI_API_KEY = ""


def test_pdf_skipped_gracefully_without_gtk():
    from app import renderers
    old = renderers._PDF_OK
    renderers._PDF_OK = False
    try:
        spec = renderers.ReportSpec(title="T", columns=["A", "B"], rows=[["x", 1.0]])
        out = renderers.render(spec, ["table", "pdf", "excel"])
        assert out["pdf_skipped"] and [f["format"] for f in out["files"]] == ["excel"]
    finally:
        renderers._PDF_OK = old


def test_spoken_messages_get_spoken_style_instruction():
    from types import SimpleNamespace
    agent.client = FakeClaude([([SimpleNamespace(type="text", text="Ji, aaj scrap 9.5 percent hai.")], "end_turn")])
    agent.handle_message(admin(), "aaj ka scrap?", "web", "web:spk", spoken=True)
    sent = agent.client.calls[0]
    assert "will HEAR your final message" in sent["messages"][-1]["content"]
    assert "feminine first-person" in sent["system"][0]["text"]


def test_voice_falls_back_when_gemini_busy():
    import base64 as _b64

    import httpx
    from app import config, voice
    config.GEMINI_API_KEY = "test-key"
    voice.time.sleep = lambda s: None
    tried = []

    def handler(req):
        import json as _json
        m = _json.loads(req.content)["model"]
        tried.append(m)
        if m == "gemini-3.8-flash":
            return httpx.Response(503, json={"error": {"message": "high demand", "code": "service_unavailable"}})
        return httpx.Response(200, json={"steps": [{"type": "model_output", "content": [{"type": "text", "text": "kal ka dispatch"}]}]})
    voice._http = httpx.Client(transport=httpx.MockTransport(handler))
    assert voice.transcribe(b"x", "audio/ogg") == "kal ka dispatch"
    assert tried == ["gemini-3.8-flash", "gemini-3.8-flash", "gemini-3.6-flash"]     # retry once, then next model

    voice._http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(400, json={"error": "bad key"})))
    try:
        voice.transcribe(b"x", "audio/ogg"); raise AssertionError("should fail")
    except voice.VoiceError as e:
        assert "400" in str(e)                                                         # real errors are not retried
    config.GEMINI_API_KEY = ""


# ------------------------------------------------------------- Gemini Live bridge (simulated session)
def test_live_voice_bridge_with_tool_call():
    import asyncio as _aio
    import base64 as _b64
    from types import SimpleNamespace as NS

    from fastapi.testclient import TestClient
    from app import config, live
    from app.main import app

    class FakeSession:
        def __init__(self):
            self.q = _aio.Queue(); self.audio_in = 0; self.tool_responses = []
            self.q.put_nowait(NS(server_content=NS(model_turn=None, input_transcription=NS(text="aaj ka scrap kitna hai"),
                                                   output_transcription=None, interrupted=False, turn_complete=False), tool_call=None))
            self.q.put_nowait(NS(server_content=None, tool_call=NS(function_calls=[
                NS(id="c1", name="get_company_data", args={"question": "aaj ka scrap kitna hai"})])))
        async def send_realtime_input(self, **kw):
            if kw.get("audio"):
                self.audio_in += 1
        async def send_tool_response(self, function_responses):
            self.tool_responses += function_responses
            part = NS(inline_data=NS(data=b"\x01\x02" * 50))
            self.q.put_nowait(NS(server_content=NS(model_turn=NS(parts=[part]), input_transcription=None,
                                                   output_transcription=NS(text="Ji, aaj scrap 9.5 percent hai."),
                                                   interrupted=False, turn_complete=True), tool_call=None))
        async def receive(self):
            m = await self.q.get()
            yield m

    fake = FakeSession()

    class CM:
        async def __aenter__(self): return fake
        async def __aexit__(self, *a): return False

    live._connect = lambda user, lang, nb, model=None: CM()
    config.GEMINI_API_KEY, config.LIVE_ENABLED, config.LIVE_VOICE_MODE = "k", True, "native"
    agent.client = FakeClaude([([text("Aaj ka overall scrap 9.5 percent hai.")], "end_turn")])
    u = store.add_user("Live User", "manager")
    store.set_login(u["id"], "liveuser", "LivePass123")
    with TestClient(app) as c:
        tok = c.post("/api/login", json={"username": "liveuser", "password": "LivePass123"}).json()["token"]
        assert c.get("/api/me", headers={"Authorization": "Bearer " + tok}).json()["live"] is True
        with c.websocket_connect(f"/api/live?token={tok}&lang=hi-IN") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json({"type": "audio", "data": _b64.b64encode(b"\x00\x00" * 160).decode()})
            seen = []
            while True:
                m = ws.receive_json(); seen.append(m["type"])
                if m["type"] == "report":
                    assert "9.5" in m["reply"]["text"]
                if m["type"] == "turn":
                    break
            ws.send_json({"type": "end"})
        assert {"heard", "tool", "report", "audio", "said", "turn"} <= set(seen), seen
        assert fake.audio_in == 1 and fake.tool_responses[0].name == "get_company_data"
        assert "9.5" in fake.tool_responses[0].response["answer"]
        # spoken-style instruction reached Claude
        assert "will HEAR" in agent.client.calls[0]["messages"][-1]["content"]
        # "tts" mode: same voice as chat - Live audio dropped, her words come back as mp3 clips
        from app import voice as _voice
        spoken = []
        _voice.speak = lambda t, lang=None, fmt="audio/mp3": spoken.append(t) or b"ID3fake"
        config.LIVE_VOICE_MODE = "tts"
        fake.__init__()
        agent.client = FakeClaude([([text("Aaj ka overall scrap 9.5 percent hai.")], "end_turn")])
        with c.websocket_connect(f"/api/live?token={tok}&lang=hi-IN") as ws:
            assert "same as chat" in ws.receive_json()["voice"]
            seen = []
            while "clip" not in seen:
                seen.append(ws.receive_json()["type"])
            ws.send_json({"type": "end"})
        assert "audio" not in seen and spoken == ["Ji, aaj scrap 9.5 percent hai."], (seen, spoken)
        config.LIVE_VOICE_MODE = "native"
        with c.websocket_connect("/api/live?token=bad") as ws:                 # no login -> refused
            assert ws.receive_json()["type"] == "error"
    config.GEMINI_API_KEY = ""


# ------------------------------------------------------------- Final production / rejection engine
def test_final_production_engine_matches_dashboard_rules():
    import datetime as _dt
    import json as _json
    from sqlalchemy import text as _t
    from app import datadb
    from app.engines import final_production as fp

    assert fp.classify_rejp("FG-A", "") == "A" and fp.classify_rejp("X", "PRIME - A") == "A"
    assert fp.classify_rejp("F-B", "") == "B" and fp.classify_rejp("Z", "SEMI REJECT - B") == "B"
    assert fp.classify_rejp("3-C", "") == "C" and fp.classify_rejp("Q", "FINAL REJECT - C") == "C"
    assert fp.classify_rejp("REW1", "") == "Rework" and fp.classify_rejp("P", "PICKLE YARD") == "Rework" and fp.classify_rejp("P", "PICKLING") == "Rejection"
    assert fp.classify_rejp("SCR9", "SCRAP YARD") == "Rejection"
    assert fp.normalize_item_group("Seamless U-Tube") == "FG Seamless"

    with datadb.engine.begin() as c:
        c.execute(_t("DROP TABLE IF EXISTS VIEW_REJECTION_PBI"))
        c.execute(_t("CREATE TABLE VIEW_REJECTION_PBI (DIVISION TEXT, TNATURE TEXT, PRODUCTION_DATE TEXT, "
                     "PLANT_CODE TEXT, ITEM_GROUP_NAME TEXT, GODOWN_CODE TEXT, GODOWN_NAME TEXT, PROD_WT_MT REAL)"))
        rows = [("U1", "PROD", "2026-10-02", "P1", "FG Welded", "OK", "FG", 90.0),
                ("U1", "REJP", "2026-10-02", "P1", "FG Welded", "FG-A", "PRIME - A", 4.0),
                ("U1", "REJP", "2026-10-03", "P1", "FG Welded", "REW1", "REWORK", 3.0),
                ("U1", "REJP", "2026-10-03", "P1", "FG Welded", "SCR", "SCRAP", 3.0),
                ("U2", "PROD", "2026-10-05", "P2", "Seamless U-Tube", "OK", "FG", 50.0),
                ("U2", "REJP", "2026-10-05", "P2", "Seamless U-Tube", "F-C", "FINAL REJECT - C", 50.0),
                ("U1", "ISSU", "2026-10-05", "P1", "X", "", "", 999.0),          # ignored
                ("U3", "PROD", "2026-10-05", "P9", "X", "", "", 999.0),          # ignored
                ("U1", "PROD", "2026-09-10", "P1", "FG Welded", "OK", "FG", 80.0),   # previous month
                ("U1", "REJP", "2026-09-10", "P1", "FG Welded", "SCR", "SCRAP", 20.0)]
        c.execute(_t("INSERT INTO VIEW_REJECTION_PBI VALUES (:a,:b,:c,:d,:e,:f,:g,:h)"),
                  [dict(zip("abcdefgh", r)) for r in rows])
    datadb.refresh_schema_cache()
    sk = _json.load(open("examples/skills/final_production_rejection_report.json"))
    store.save_skill(sk, changed_by="test")
    u = store.add_user("FP User", "manager")
    ctx = agent.Ctx(user=u, role=store.get_role("manager"), channel="web", chat_key="fp", request_text="final rejection oct")
    r = agent._tool_run_report_engine(ctx, "final_production_rejection_report", "2026-10-01", "2026-10-31")
    assert "error" not in r, r
    k = r["kpis_by_unit"]
    assert k["U1"]["tot"] == 100 and k["U1"]["yield_pct"] == 90 and k["U1"]["A"] == 4 and k["U1"]["rew"] == 3
    assert k["U2"]["C"] == 50 and k["ALL"]["tot"] == 200 and k["ALL"]["rejp_pct"] == 30
    assert k["U1"]["prev"]["yield_pct"] == 80                                  # compared with September
    assert all(c["ok"] for c in r["checks"])
    assert {"excel", "dashboard"} <= set(r["files_created"])
    dash = next(f for f in ctx.reply.files if f["format"] == "dashboard")
    html = open(dash["path"], encoding="utf-8").read()
    assert "processRawRows([" in html and '"Seamless U-Tube"' in html            # user's dashboard, data pre-loaded
    u1 = {c["label"]: c for c in ctx.reply.kpis if c.get("group") == "Welded (U1)"}
    assert list(u1) == ["Inspection Qty (PROD)", "Rejection", "Rework", "A + B + C", "Subtotal REJP", "Total Inspection"]
    assert u1["Total Inspection"]["value"] == 100 and u1["Inspection Qty (PROD)"]["previous"] == 80
    m = ctx.results["fp_U1_matrix"]
    assert m["columns"][0] == "Particulars" and m["columns"][-1] == "Grand Total"
    assert [r[0] for r in m["rows"] if not r[0].startswith("   ↳")][:6] == ["Tnature PROD — Inspection Qty", "Rejection", "Rework", "A + B + C",
                                            "Subtotal (Tnature REJP)", "TOTAL INSPECTION (Grand Total)"]
    assert next(r for r in m["rows"] if r[0] == "TOTAL INSPECTION (Grand Total)")[-1] == 100
    kids = [r for r in m["rows"] if r[0].startswith("   ↳")]
    assert kids and abs(sum(r[-1] or 0 for r in kids) - 100) < 1e-6      # godown rows add up to total inspection
    msg, s = agent.expand_slash("/final-production-rejection-report sep", u)         # hyphen name works
    assert s and s["name"] == "final_production_rejection_report" and "sep" in msg


def test_final_production_real_view_shape():
    """The live view: DIV_CODE, VRDATE as Oracle text, 'Production Qty (MT)' - same as the V10 HTML reads."""
    import json as _json
    from sqlalchemy import text as _t
    from app import datadb
    with datadb.engine.begin() as c:
        c.execute(_t("DROP TABLE IF EXISTS VIEW_REJECTION_PBI"))
        c.execute(_t('CREATE TABLE VIEW_REJECTION_PBI (DIV_CODE TEXT, TNATURE TEXT, VRDATE TEXT, VRNO TEXT, PLANT_CODE TEXT, '
                     'ITEM_GROUP_NAME TEXT, GODOWN_CODE TEXT, GODOWN_NAME TEXT, VR_MONTH TEXT, '
                     '"Production Qty (KG)" REAL, "Production Qty (MT)" REAL)'))
        rows = [("U1", "PROD", "09-OCT-2026", "P1", "FG Welded", "OK", "FG", 90000.0, 90.0),
                ("U1", "REJP", "10-OCT-26", "P1", "FG Welded", "SCR", "SCRAP", 10000.0, 10.0),
                ("u2", "PROD", "01-OCT-2026", "P2", "FG Seamless", "OK", "FG", 40000.0, 40.0),
                ("U1", "PROD", "10-SEP-2026", "P1", "FG Welded", "OK", "FG", 5000.0, 5.0)]     # previous month
        c.execute(_t("INSERT INTO VIEW_REJECTION_PBI VALUES (:a,:b,:c,'V',:d,:e,:f,:g,'OCT',:h,:i)"),
                  [dict(zip("abcdefghi", r)) for r in rows])
    datadb.refresh_schema_cache()
    sk = _json.load(open("examples/skills/final_production_rejection_report.json"))
    store.save_skill(sk, changed_by="test")
    u = store.add_user("FP Real", "manager")
    ctx = agent.Ctx(user=u, role=store.get_role("manager"), channel="web", chat_key="fpr", request_text="final rejection oct")
    r = agent._tool_run_report_engine(ctx, "final_production_rejection_report", "2026-10-01", "2026-10-27")
    assert "error" not in r, r
    k = r["kpis_by_unit"]
    assert k["U1"]["tot"] == 100 and k["U2"]["tot"] == 40 and k["U1"]["prev"]["tot"] == 5
    from app.engines import final_production as fpe
    sk2 = store.get_skill("final_production_rejection_report")
    o2 = fpe.run(sk2, "2026-10-01", "2026-10-27", ["*"], division="U2")       # U2 only: v11 page, opens on U2, no U1 rows
    page = o2["files"]["dashboard"].decode()
    assert "<title>" in page and "processRawRows" in page and '"U2"' in page and "x.style.display='none'" in page
    assert '"Division": "U1"' not in page and '"Division": "U2"' in page
    r2 = agent._tool_run_report_engine(ctx, "final_production_rejection_report", "2026-11-01", "2026-11-30")
    assert "U1/PROD" in r2["error"] and "VRDATE" in r2["error"]          # empty month explains what the view holds


# ------------------------------------------------------------- Job cardwise scrap engine (v4 HTML rules)
def test_jobcard_scrap_engine_rules_and_dashboard():
    import json as _json
    from sqlalchemy import text as _t
    from app import datadb
    from app.engines import jobcard_scrap as jc

    assert jc.norm_process("PEELI - PEELING") == "PEELING" and jc.norm_process("MOTHE - MH CUTTING") == "MOTHER HOLLOW CUTTING"
    assert jc.norm_process("CUTTI - CUTTING & DEBURRING") == "FINAL CUTTING & DEBURRING"
    assert jc.norm_process("PILGE - PILGERING") == "PILGER" and jc.norm_process("FINSP - FINAL INSPECTION") == "FINAL INSPECTION"
    with datadb.engine.begin() as c:
        c.execute(_t("DROP TABLE IF EXISTS VIEW_JOB_CARD_SCRAP_PBI"))
        c.execute(_t("CREATE TABLE VIEW_JOB_CARD_SCRAP_PBI (JOB_CARD_NO TEXT, PROCESS_NAME TEXT, PLANT_NAME TEXT, "
                     "ITEM_GROUP TEXT, PROD_DATE TEXT, MACHINE_NAME TEXT, SCRAP_QTY REAL, PROD_QTY_WITH_SCRAP REAL)"))
        rows = [("J1", "PEELI - PEELING", "BA", "ROUND BAR", "2026-10-02", "M1", 20, 1000),
                ("J1", "ROUND - RB CUTTING", "BA", "ROUND BAR", "2026-10-02", "M1", 30, 980),          # 50/1000 = 5%
                ("J2", "PIERC - PIERCING", "SEAMLESS PIPE- 1", "MOTHER HOLLOW", "2026-10-03", "M2", 100, 2000),
                ("J2", "FINSP - FINAL INSPECTION", "BA", "MOTHER HOLLOW", "2026-10-03", "M2", 500, 1900),  # BA excluded on FI
                ("J3", "FINSP - FINAL INSPECTION", "SEAMLESS PIPE- 1", "ROUND BAR", "2026-10-03", "M2", 9, 100),  # not Mother Hollow
                ("J4", "PILGE - PILGERING", "SEAMLESS TUBE", "TUBE", "2026-10-04", "M3", 250, 1000),
                ("J4", "SINKI - SINKING", "BA", "TUBE", "2026-10-04", "M3", 10, 500),                # 2 plants -> 2 rows
                ("J5", "MACHI - MACHINING", "BA", "X", "2026-10-04", "M9", 999, 5000)]              # excluded
        c.execute(_t("INSERT INTO VIEW_JOB_CARD_SCRAP_PBI VALUES (:a,:b,:c,:d,:e,:f,:g,:h)"),
                  [dict(zip("abcdefgh", r)) for r in rows])
    datadb.refresh_schema_cache()
    sk = _json.load(open("examples/skills/jobcardwise_scrap.json"))
    store.save_skill(sk, changed_by="test")
    u = store.add_user("JC User", "manager")
    assert agent.find_skill_by_command("jobcardwise-scrap%-report")["name"] == "jobcardwise_scrap"
    ctx = agent.Ctx(user=u, role=store.get_role("manager"), channel="web", chat_key="jc", request_text="jobcard oct")
    r = agent._tool_run_report_engine(ctx, "jobcardwise_scrap", "2026-10-01", "2026-10-31")
    assert "error" not in r, r
    sec = r["summary"]["sections"]
    assert sec["bb2bb"]["buckets"]["5% - 8%"] == 1 and sec["bb2bb"]["scrap_pct"] == 5.0
    assert sec["bb2hollow"]["job_cards"] == 1 and sec["bb2hollow"]["scrap_pct"] == 5.0          # J3 dropped, FI@BA dropped
    assert sec["cutting"]["job_cards"] == 2 and sec["cutting"]["buckets"]["Above 20%"] == 1      # J4 split by plant
    assert r["summary"]["overall"]["jobs"] == 4                                                  # machining-only J5 excluded
    assert all(c["ok"] for c in r["checks"]) and set(r["files_created"]) == {"chart", "dashboard"}
    html = open(next(f for f in ctx.reply.files if f["format"] == "dashboard")["path"], encoding="utf-8").read()
    assert "inp.dispatchEvent(new Event('change'" in html and "Job Cardwise" in html
    r2 = agent._tool_run_report_engine(ctx, "jobcardwise_scrap", "2026-10-01", "2026-10-31", unit="mt", formats=["table", "excel"])
    assert r2["files_created"] == ["excel"] and r2["unit"] == "MT"


# ------------------------------------------------------------- private views (employee master)
def test_private_view_blocked_for_non_admin():
    from sqlalchemy import text as _t
    from app import datadb
    with datadb.engine.begin() as c:
        c.execute(_t("DROP TABLE IF EXISTS VIEW_EMP_MAST_PBI"))
        c.execute(_t("CREATE TABLE VIEW_EMP_MAST_PBI (EMP_NAME TEXT, SALARY REAL)"))
    datadb.refresh_schema_cache()
    deny = ["*", "!VIEW_EMP_MAST_PBI"]
    for sql in ("SELECT * FROM VIEW_EMP_MAST_PBI",
                "SELECT * FROM view_emp_mast_pbi",
                "WITH VIEW_EMP_MAST_PBI AS (SELECT * FROM VIEW_EMP_MAST_PBI) SELECT * FROM VIEW_EMP_MAST_PBI",
                "WITH x AS (SELECT * FROM VIEW_EMP_MAST_PBI) SELECT * FROM x"):
        try:
            datadb.validate_select(sql, deny); raise AssertionError("not blocked: " + sql)
        except datadb.SQLRejected as e:
            assert "PRIVATE" in str(e)
    assert "VIEW_EMP_MAST_PBI" not in datadb.list_tables(deny)
    datadb.validate_select("SELECT * FROM VIEW_EMP_MAST_PBI", ["*"])          # admin: allowed
    # allow-list roles: CTE named like a forbidden table cannot hide it
    try:
        datadb.validate_select("WITH VIEW_EMP_MAST_PBI AS (SELECT * FROM VIEW_EMP_MAST_PBI) SELECT * FROM VIEW_EMP_MAST_PBI", ["sales"])
        raise AssertionError("CTE loophole open")
    except datadb.SQLRejected:
        pass
    # the agent adds the lock for a manager automatically
    u = store.add_user("Priv User", "manager")
    agent.client = FakeClaude([([text("ok")], "end_turn")])
    agent.handle_message(u, "employee list do", "web", "priv")


# ------------------------------------------------------------- live dashboards for HODs (signed links, no upload)
def test_live_dashboard_links():
    import json as _json
    from fastapi.testclient import TestClient
    from sqlalchemy import text as _t
    from app import dash, datadb
    from app.main import app
    with datadb.engine.begin() as c:
        c.execute(_t("DROP TABLE IF EXISTS VIEW_REJECTION_PBI"))
        c.execute(_t("CREATE TABLE VIEW_REJECTION_PBI (DIVISION TEXT, TNATURE TEXT, PRODUCTION_DATE TEXT, PLANT_CODE TEXT, "
                     "ITEM_GROUP_NAME TEXT, GODOWN_CODE TEXT, GODOWN_NAME TEXT, PROD_WT_MT REAL)"))
        c.execute(_t("INSERT INTO VIEW_REJECTION_PBI VALUES ('U1','PROD','2026-09-03','P1','FG Welded','OK','FG',90),"
                     "('U1','REJP','2026-09-03','P1','FG Welded','FG-A','PRIME - A',10)"))
    datadb.refresh_schema_cache()
    store.save_skill(_json.load(open("examples/skills/final_production_rejection_report.json")), changed_by="t")
    u = store.add_user("HOD One", "viewer")
    k = dash.make_token(u["id"])
    assert dash.check_token(k)["id"] == u["id"] and dash.check_token(k[:-2] + "xx") is None
    with TestClient(app) as c:
        c.cookies.set("rb_sess", store.create_session(u["id"], 1))       # the link's own user, signed in
        assert c.get("/dash?k=bad").status_code == 401
        page = c.get(f"/dash?k={k}").text
        assert "Final Production / Rejection" in page and "/dash/final-production?k=" in page
        r = c.get(f"/dash/final-production?k={k}&month=2026-09")
        assert "Preparing your live dashboard" in r.text                      # spinner first
        r = c.get(f"/dash/final-production?k={k}&month=2026-09&go=1")
        assert r.status_code == 200, r.text[:300]
        assert "● LIVE" in r.text and "processRawRows([" in r.text and "SEP 2026" in r.text
        tok = c.post("/api/login", json={"username": "admin", "password": "AdminPass123"}) if False else None


# ------------------------------------------------------------- streaming answers, exact maths, follow-ups, briefing
def test_stream_events_calculate_and_followups():
    import json as _json
    from fastapi.testclient import TestClient
    from app.main import app
    agent.client = FakeClaude([
        ([text("Let me calculate."), tool_use("calculate", {"expressions": {"forecast": "4218.1/25*31", "bad": "__import__('os')"}}, 91),
          tool_use("show_kpi_cards", {"kpis": [{"label": "Forecast MT", "value": 5230.4, "unit": "MT"}]}, 92)], "tool_use"),
        ([tool_use("suggest_followups", {"items": ["Why is P21 high?", "Compare with last month", "Draft mail", "extra"]}, 93)], "tool_use"),
        ([text("Month-end projection is about 5,230 MT.")], "end_turn")])
    u = store.add_user("Stream User", "manager")
    store.set_login(u["id"], "streamer", "StreamPass123")
    with TestClient(app) as c:
        tok = c.post("/api/login", json={"username": "streamer", "password": "StreamPass123"}).json()["token"]
        h = {"Authorization": "Bearer " + tok}
        r = c.post("/api/chat/stream", json={"message": "month end forecast"}, headers=h)
        evs = [_json.loads(l[6:]) for l in r.text.splitlines() if l.startswith("data: ")]
        types = [e["type"] for e in evs]
        assert "step" in types and "figure" in types and types[-1] == "reply", types
        calc = next(e for e in evs if e["type"] == "step" and e.get("name") == "calculate" and e["status"] == "done")
        assert "forecast = 5230.444" in calc["detail"]                               # exact maths, no code allowed
        fig = next(e for e in evs if e["type"] == "figure")
        assert fig["label"] == "Forecast MT" and fig["source"] == "Live query"
        rep = evs[-1]
        assert rep["text"].startswith("Month-end") and rep["suggestions"] == ["Why is P21 high?", "Compare with last month", "Draft mail"]
        assert agent._tool_calculate(None, {"x": "__import__('os')"})["x"].startswith("error")
        assert c.get("/api/briefing", headers=h).json().keys() >= {"cards", "noticed"}
        me = c.get("/api/me", headers=h).json()
        assert "data_synced_at" in me


def test_department_roles():
    from sqlalchemy import text as _t
    from app import datadb
    from tools import manage
    with datadb.engine.begin() as c:
        for v in ("VIEW_TUBING_PBI", "VIEW_SCRAP_SEAMLESS_PBI", "VIEW_LD_SALES_ORDERS_PBI", "VIEW_GRN_PBI"):
            c.execute(_t(f"DROP TABLE IF EXISTS {v}")); c.execute(_t(f"CREATE TABLE {v} (QTY REAL)"))
    datadb.refresh_schema_cache()
    manage.main(["dept-roles"])
    prod = store.get_role("production")["allowed_tables"]
    datadb.validate_select("SELECT * FROM VIEW_TUBING_PBI", prod)
    datadb.validate_select("SELECT * FROM VIEW_SCRAP_SEAMLESS_PBI", prod)       # glob VIEW_SCRAP_*
    for bad in ("SELECT * FROM VIEW_LD_SALES_ORDERS_PBI", "SELECT * FROM VIEW_GRN_PBI", "SELECT * FROM VIEW_EMP_MAST_PBI"):
        try:
            datadb.validate_select(bad, prod); raise AssertionError("not blocked: " + bad)
        except datadb.SQLRejected:
            pass
    vis = datadb.list_tables(prod)
    assert "VIEW_TUBING_PBI" in vis and "VIEW_LD_SALES_ORDERS_PBI" not in vis and "VIEW_GRN_PBI" not in vis
    acc = store.get_role("accounts")["allowed_tables"]
    datadb.validate_select("SELECT * FROM VIEW_LD_SALES_ORDERS_PBI", acc)
    try:
        datadb.validate_select("SELECT * FROM VIEW_EMP_MAST_PBI", acc); raise AssertionError("emp open")
    except datadb.SQLRejected:
        pass
    # report list follows the department
    store.save_skill({"name": "seamless_production", "title": "Seamless Production", "rules": "Use VIEW_TUBING_PBI",
                      "output_format": "t"}, "t")
    bharat = store.add_user("Bharat Prajapati", "production", "70001")
    rajesh = store.add_user("Rajesh", "purchase", "70002")
    names = lambda u: {s["name"] for s in store.list_skills(u)}
    assert "seamless_production" in names(bharat)
    assert "seamless_production" not in names(rajesh)
    store.set_user_role(rajesh["id"], "accounts")
    assert "seamless_production" in names(store.get_user(rajesh["id"]))


def test_combined_role():
    from tools import manage
    manage.main(["dept-roles"])
    manage.main(["add-role", "prod_stock", "production,VIEW_ITEM_LEDGER_PBI,sales"])
    t = store.get_role("prod_stock")["allowed_tables"]
    assert "VIEW_TUBING_PBI" in t and "VIEW_ITEM_LEDGER_PBI" in t and "VIEW_LD_SALES_ORDERS_PBI" in t
    assert t.count("!VIEW_EMP_MAST_PBI") == 1 and "*" not in t


def test_export_users(tmp_path):
    from openpyxl import load_workbook
    from tools import manage
    manage.main(["dept-roles"])
    out = tmp_path / "u.xlsx"
    manage.main(["export-users", str(out)])
    wb = load_workbook(out)
    assert wb.sheetnames == ["Users", "Roles"]
    assert [c.value for c in wb["Users"][1]][:3] == ["#", "Name", "Role"]
    assert wb["Users"].max_row >= 2 and wb["Roles"].max_row >= 7


def test_delete_user():
    from tools import manage
    u = store.add_user("Temp Person", "viewer", "99887766")
    store.add_message(f"tg:99887766", "user", "hi")
    manage.main(["delete-user", str(u["id"]), "--yes"])
    assert store.get_user(u["id"]) is None
    assert store.recent_messages("tg:99887766", 5) == []
    manage.main(["set-role", str(store.add_user("Promote Me", "manager")["id"]), "admin"])


def test_scrap_mis_engine():
    """Scrap MIS v10 port: 4 views -> the tool's lines, KPIs and an auto-uploading dashboard."""
    import json as _j
    from sqlalchemy import text as _t
    from app import datadb
    from app.engines import scrap_mis
    with datadb.engine.begin() as c:
        for v in ("VIEW_SEAMLESS_SCRAP_MIS_PBI", "VIEW_SLITTING_MIS_PBI", "VIEW_FINAL_CUTTING_SCRAP_PBI", "VIEW_M2M_PBI"):
            c.execute(_t(f"DROP TABLE IF EXISTS {v}"))
        c.execute(_t("CREATE TABLE VIEW_SEAMLESS_SCRAP_MIS_PBI (MACHINE_NAME TEXT, PLANT TEXT, PRODUCTION_DATE TEXT, PROD_QTY REAL, RL_QTY REAL, SCRAP_QTY REAL, BL_QTY REAL)"))
        c.execute(_t("CREATE TABLE VIEW_SLITTING_MIS_PBI (PRODUCTION_DATE TEXT, ITEM_GROUP_NAME TEXT, GODOWN_NAME TEXT, ISSUE_QUANTITY REAL, RECEIVED_QUANTITY REAL)"))
        c.execute(_t("CREATE TABLE VIEW_FINAL_CUTTING_SCRAP_PBI (PROCESS_NAME TEXT, PLANT_NAME TEXT, PLANT_CODE TEXT, PROD_DATE TEXT, MACHINE_NAME TEXT, PROD_QTY_KG REAL, SCARP_QTY REAL)"))
        c.execute(_t("CREATE TABLE VIEW_M2M_PBI (TRANSACTION_DATE TEXT, GODOWN_NAME TEXT, RECEIVED_QUANTITY REAL)"))
        ins = lambda t, rows: [c.execute(_t(f"INSERT INTO {t} VALUES ({','.join(':' + str(i) for i in range(len(r)))})"),
                                         {str(i): x for i, x in enumerate(r)}) for r in rows]
        ins("VIEW_SEAMLESS_SCRAP_MIS_PBI", [("W1", "WELDE", "2026-10-02", 10000, 100, 300, 50), ("TM10", "WELDE", "2026-10-03", 2000, 0, 40, 0),
                                            ("PLB1", "L_SAW", "2026-10-03", 5000, 0, 100, 0), ("EXP1", "SMLSP", "2026-10-04", 3000, 30, 90, 0),
                                            ("PEEL1", "SMLSP", "2026-10-04", 4000, 0, 200, 0), ("PIL1", "SMLSP", "2026-10-05", 6000, 60, 120, 30),
                                            ("Q", "ZZZZ", "2026-10-05", 999, 0, 9, 0), ("W1", "WELDE", "2026-09-10", 8000, 0, 400, 0)])
        ins("VIEW_SLITTING_MIS_PBI", [("2026-10-02", "SS COIL", "Main", 5000, 4800), ("2026-10-02", "SS SCRAP", "Outside", 0, 200)])
        ins("VIEW_FINAL_CUTTING_SCRAP_PBI", [("CUTTING & DEBURRING", "Welded", "WELDE", "2026-10-06", "C1", 9000, 300),
                                             ("MH CUTTING", "Seamless Pipe-1", "SMLSP", "2026-10-06", "C2", 1000, 50),
                                             ("CUTTING WO PROCESS-MH", "Seamless Pipe-1", "SMLSP", "2026-10-06", "C3", 700, 70)])
        ins("VIEW_M2M_PBI", [("2026-10-07", "M2M", 250)])
    datadb.refresh_schema_cache()
    out = scrap_mis.run({"sql_template": _j.dumps({"engine": "scrap_mis"})}, "2026-10-01", "2026-10-31", ["*"])
    o = out["_internal"]["out"]
    assert o["W_WELDED"]["p"][0] == 10000 and o["W_TM10"]["p"][0] == 2000 and o["L_LSAW"]["p"][0] == 5000
    assert o["W_SLIT"]["p"][0] == 4800 and o["W_SLIT"]["p"][2] == 200
    assert o["T_WELDED"]["p"][0] == 10000 + 2000 + 4800            # L-Saw not added into welded total
    assert o["S_PIPE1_EXP1"]["p"][0] == 3000 and o["S_PIPE1_PEEL"]["p"][0] == 4000 and o["S_PIPE1_PIL"]["p"][0] == 6000
    assert o["W_WELDED"]["c"][:2] == [9000, 300] and o["S_PIERC"]["c"][:2] == [1000, 50] and o["S_OTH"]["c"][1] == 250
    assert any(e["label"].startswith("Cutting WO Process") for e in out["summary"]["left_out"])
    assert any("ZZZZ" in e["label"] for e in out["summary"]["left_out"])
    k = {c["label"]: c for c in out["kpis"]}
    assert k["Welded production"]["value"] == 16.8 and k["Welded production"]["previous"] == 8.0
    assert all(c["ok"] for c in out["checks"])
    page = out["files"]["dashboard"].decode()
    assert "fileIn" in page and "Welded.csv" in page and "M2M.csv" in page and "Final_Cutting.csv" in page


def test_division_lock_u2_only():
    """A user locked to U2 (Seamless) gets only U2 numbers - in Scrap MIS, Final Rejection, free SQL and sending."""
    import json as _j
    from app.engines import scrap_mis
    test_scrap_mis_engine()                                       # same sample views
    out = scrap_mis.run({"sql_template": _j.dumps({"engine": "scrap_mis"})}, "2026-10-01", "2026-10-31", ["*"], division="U2")
    o = out["_internal"]["out"]
    assert o["W_WELDED"]["p"][0] == 0 and o["L_LSAW"]["p"][0] == 0 and o["W_SLIT"]["p"][0] == 0 and o["W_WELDED"]["c"][:2] == [0, 0]
    assert o["S_PIPE1_PIL"]["p"][0] == 6000 and o["S_PIERC"]["c"][:2] == [1000, 50] and o["S_OTH"]["c"][1] == 250
    labels = " ".join(k["label"] for k in out["kpis"])
    assert "Welded" not in labels and "L-Saw" not in labels and "Seamless production" in labels
    assert "welded_mt" not in out["summary"] and {s2["result_id"] for s2 in out["sections"]} <= {"seamless", "excl"}
    page = out["files"]["dashboard"].decode()
    assert "Welded.csv" not in page and "Slitting.csv" not in page and "Seamless.csv" in page
    # the user lock is applied on the server whatever is asked
    u = store.add_user("Bharat Lock", "manager")
    store.set_user_division(u["id"], "U2")
    u = store.get_user(u["id"])
    role = agent.effective_role(u)
    assert role["division_lock"] == "U2" and not role["free_query"] and "!VIEW_WELDED_*" in role["allowed_tables"]
    sk = {"name": "scrap_mis_report", "title": "Scrap MIS", "sql_template": _j.dumps({"engine": "scrap_mis"}), "allowed_roles": []}
    store.save_skill(_j.load(open("examples/skills/scrap_mis_report.json")), changed_by="test")
    ctx = agent.Ctx(user=u, role=role, channel="web", chat_key="lock", request_text="scrap mis oct welded")
    r = agent._tool_run_report_engine(ctx, "scrap_mis_report", "2026-10-01", "2026-10-31", division="U1")   # asks for welded
    assert "error" not in r, r
    assert not any("Welded" in k["label"] for k in ctx.reply.kpis) and ctx.built_division == "U2"
    assert "error" in agent._tool_run_sql(ctx, "SELECT * FROM VIEW_SEAMLESS_SCRAP_MIS_PBI")
    # sending a full (both-division) report to him is refused
    boss = store.get_user(1)
    store.set_user_contact(u["id"], email="bharat@x.com")
    bctx = agent.Ctx(user=boss, role=agent.effective_role(boss), channel="web", chat_key="b", request_text="x")
    agent._tool_run_report_engine(bctx, "scrap_mis_report", "2026-10-01", "2026-10-31")
    from app import outbox
    outbox_ready = outbox.channel_ready
    outbox.channel_ready = lambda ch: ""
    try:
        res = agent._tool_send_files(bctx, "email", ["Bharat Lock"])
        assert "error" in res and "only U2" in res["error"], res
        agent._tool_run_report_engine(bctx, "scrap_mis_report", "2026-10-01", "2026-10-31", division="U2")
        bctx.reply.files = bctx.reply.files[-3:]
        res2 = agent._tool_send_files(bctx, "email", ["Bharat Lock"])
        assert res2.get("needs_confirmation"), res2
    finally:
        outbox.channel_ready = outbox_ready


def test_scrap_mis_welded_view():
    """With VIEW_WELDED_SCRAP_MIS_PBI present, Welded.csv comes from it and the seamless view is the Seamless file only."""
    import json as _j
    from sqlalchemy import text as _t
    from app import datadb
    from app.engines import scrap_mis
    test_scrap_mis_engine()                      # builds the other 4 views
    with datadb.engine.begin() as c:
        c.execute(_t("DROP TABLE IF EXISTS VIEW_WELDED_SCRAP_MIS_PBI"))
        c.execute(_t("CREATE TABLE VIEW_WELDED_SCRAP_MIS_PBI (MACHINE_NAME TEXT, PLANT_CODE TEXT, PRODUCTION_DATE TEXT, PROD_QTY REAL, SCRAP_QTY REAL)"))
        c.execute(_t("INSERT INTO VIEW_WELDED_SCRAP_MIS_PBI VALUES ('W9','WELDE','2026-10-09',7000,70), ('C1','CONDT','2026-10-09',1000,10)"))
    datadb.refresh_schema_cache()
    out = scrap_mis.run({"sql_template": _j.dumps({"engine": "scrap_mis"})}, "2026-10-01", "2026-10-31", ["*"])
    o = out["_internal"]["out"]
    assert o["W_WELDED"]["p"][0] == 7000 and o["W_COND"]["p"][0] == 1000 and o["W_TM10"]["p"][0] == 0
    assert "welded_source_note" not in out["summary"]
    assert any("WELDE" in e["label"] for e in out["summary"]["left_out"])   # welded rows in the seamless file: no seamless line
    with datadb.engine.begin() as c:
        c.execute(_t("DROP TABLE VIEW_WELDED_SCRAP_MIS_PBI"))
    datadb.refresh_schema_cache()


def test_scrap_mis_text_dates():
    """Views whose date column is text ('01-OCT-2026') must still be filtered by period."""
    import json as _j
    from sqlalchemy import text as _t
    from app import datadb
    from app.engines import scrap_mis
    from tools import manage
    test_scrap_mis_engine()
    with datadb.engine.begin() as c:
        c.execute(_t("DROP TABLE IF EXISTS VIEW_WELDED_SCRAP_MIS_PBI"))
        c.execute(_t("CREATE TABLE VIEW_WELDED_SCRAP_MIS_PBI (MACHINE_NAME TEXT, PLANT_CODE TEXT, PROD_DATE VARCHAR(20), PROD_QTY REAL, SCRAP_QTY REAL)"))
        c.execute(_t("INSERT INTO VIEW_WELDED_SCRAP_MIS_PBI VALUES ('W9','WELDE','09-OCT-2026',7000,70), ('W9','WELDE','09-SEP-2026',5000,50)"))
    datadb.refresh_schema_cache()
    out = scrap_mis.run({"sql_template": _j.dumps({"engine": "scrap_mis"})}, "2026-10-01", "2026-10-31", ["*"])
    assert out["_internal"]["out"]["W_WELDED"]["p"][0] == 7000
    assert out["summary"]["views"]["VIEW_WELDED_SCRAP_MIS_PBI"]["records"] == 1
    manage.main(["check-scrap-mis", "2026-10"])
    with datadb.engine.begin() as c:
        c.execute(_t("DROP TABLE VIEW_WELDED_SCRAP_MIS_PBI"))
    datadb.refresh_schema_cache()


def test_sales_order_engine():
    """Sales Order MIS: view rows -> the generator's data model, KPIs, overdue lines, SP matrix, dashboard with data."""
    import json as _j
    from sqlalchemy import text as _t
    from app import datadb
    from app.engines import sales_order as so
    with datadb.engine.begin() as c:
        c.execute(_t("DROP TABLE IF EXISTS VIEW_SALES_ORDER_PBI"))
        c.execute(_t("CREATE TABLE VIEW_SALES_ORDER_PBI (SALES_ORDER_NO TEXT, SALES_ORDER_DATE TEXT, DELIVERY_DATE TEXT, ITEM_GROUP_NAME TEXT, "
                     "CUSTOMER_NAME TEXT, SALES_PERSON_NAME TEXT, PARENT_GRADE TEXT, GRADE TEXT, UM TEXT, SALE_ORDER_QTY_KG REAL, CANCELLED_QTY REAL, "
                     "NET_ORDER_QTY_KG REAL, DISP_QUANTITY_KG REAL, BAL_SALES_ORDER_QTY REAL, DELAY_DURATION TEXT, DELAY_DELIVERY_QTY REAL, "
                     "MATERIAL_VALUE_INR REAL, LD_APPLICABLE TEXT, CLOSED_FLAG TEXT)"))
        rows = [("SO1", "05-OCT-26", "2026-10-10", "FG SEAMLESS PIPE", "acme", "Rakesh", "316L", "X", "KG", 10000, 0, 10000, 6000, 4000, "A:3, B:9", 9999, 5000000, "Yes", ""),
                ("SO2", "2026-10-06", "2099-01-01", "FG WELDED PIPE", "beta", "", "", "X", "KG", 5000, 1000, 4000, 0, 4000, "", 0, 1200000, "no", "Partialy Cancelled"),
                ("SO3", "06-Oct-2026", "2026-10-07", "PIPE FITTINGS", "acme", "Rakesh", "304", "X", "NO", 50, 0, 50, 50, 0, "", 0, 250000, "", "Closed Permanently"),
                ("SO4", "2025-10-05", "2025-10-20", "FG SEAMLESS PIPE", "acme", "Rakesh", "316L", "X", "KG", 8000, 0, 8000, 8000, 0, "", 0, 4000000, "Yes", "")]
        for r in rows:
            c.execute(_t("INSERT INTO VIEW_SALES_ORDER_PBI VALUES (" + ",".join(f":{i}" for i in range(len(r))) + ")"), {str(i): v for i, v in enumerate(r)})
    datadb.refresh_schema_cache()
    out = so.run({"sql_template": _j.dumps({"engine": "sales_order"})}, "2026-10-01", "2026-10-26", ["*"])
    D = out["_internal"]["D"]
    assert D["n"] == 4 and D["dict"]["grade"][:2] == ["316L", "OTHER"] or "OTHER" in D["dict"]["grade"]
    k = {c["label"]: c for c in out["kpis"]}
    assert k["Net booked"]["value"] == 14.0 and k["Net booked"]["previous"] == 8.0        # MT, fittings excluded
    assert k["Net booked value"]["value"] == round((5000000 + 1200000 + 250000) / 1e7, 2)
    assert k["Fittings (Nos)"]["value"] == 50
    assert k["Cancelled"]["value"] == 1.0
    s = out["summary"]
    assert s["executed_mt"] == 6.0 and s["pending_mt"] == 8.0 and s["overdue_mt"] == 4.0   # SO1 overdue, SO2 not due
    assert s["on_time_pct"] == 0.0                                                         # late = min(9999, 6000) = all executed
    od = out["results"]["so_overdue"]["rows"]
    assert [r[0] for r in od] == ["SO1"] and od[0][9] == "Yes"
    page = out["files"]["dashboard"].decode()
    assert '<script id="mis-data" type="application/json">{' in page
    assert all(c["ok"] for c in out["checks"])


def test_send_files_confirm_and_privacy(monkeypatch):
    from app import agent, outbox, config as cfg
    from tools import manage
    manage.main(["dept-roles"])
    sent = []
    monkeypatch.setattr(cfg, "SMTP_HOST", "smtp.test"); monkeypatch.setattr(cfg, "SMTP_FROM", "bot@test")
    monkeypatch.setattr(outbox, "send_email", lambda to, subj, body, paths: sent.append((to, paths)))
    boss = store.add_user("Send Boss", "admin")
    ravi = store.add_user("Zravi Sender", "accounts"); store.set_user_contact(ravi["id"], email="ravi@x.com")
    rajesh = store.add_user("Zrajesh Sender", "purchase"); store.set_user_contact(rajesh["id"], email="raj@x.com")
    sk = store.save_skill({"name": "send_test", "title": "Send Test Report", "rules": "Use VIEW_TUBING_PBI", "output_format": "t"}, "t")
    import tempfile, pathlib
    f = pathlib.Path(tempfile.mkdtemp()) / "r.xlsx"; f.write_bytes(b"x")
    rid = store.save_report(user_id=boss["id"], channel="web", skill_name="send_test", title="Send Test Report", request_text="",
                            sql_text="", row_count=1, summary="", files=[{"format": "excel", "filename": "r.xlsx", "path": str(f), "url": ""}], data_preview=[])
    ctx = agent.Ctx(user=store.get_user(boss["id"]), role=agent.effective_role(store.get_user(boss["id"])), channel="web",
                    chat_key="web:x", request_text="")
    r = agent._tool_send_files(ctx, "email", ["Zravi", "Zrajesh"], report_id=rid)
    assert r["needs_confirmation"] and r["to"] == ["Zravi Sender"] and any("no access" in x for x in r["skipped"]) and not sent
    r = agent._tool_send_files(ctx, "email", ["Zravi"], report_id=rid, confirmed=True)
    assert r["sent_to"] == ["Zravi Sender"] and sent == [(["ravi@x.com"], [str(f)])]
    assert "error" in agent._tool_send_files(ctx, "whatsapp", ["Zravi"], report_id=rid)     # WhatsApp not configured


def test_whatsapp_webhook(monkeypatch):
    from fastapi.testclient import TestClient
    from app import main, config as cfg, whatsapp, agent
    monkeypatch.setattr(cfg, "WHATSAPP_VERIFY_TOKEN", "venus123")
    c = TestClient(main.app)
    r = c.get("/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "venus123", "hub.challenge": "42"})
    assert r.status_code == 200 and r.text == "42"
    assert c.get("/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "bad", "hub.challenge": "1"}).status_code == 403
    u = store.add_user("Wa Person", "admin"); store.set_user_contact(u["id"], phone="9811122233")
    out = []
    monkeypatch.setattr(whatsapp, "send_text", lambda to, t: out.append((to, t)))
    monkeypatch.setattr(agent, "handle_message", lambda user, text, **kw: agent.AgentReply(text=f"hi **{user['name']}**"))
    whatsapp.process({"entry": [{"changes": [{"value": {"messages": [{"from": "919811122233", "type": "text", "text": {"body": "hello"}}]}}]}]})
    whatsapp.process({"entry": [{"changes": [{"value": {"messages": [{"from": "919800000000", "type": "text", "text": {"body": "hello"}}]}}]}]})
    assert out[0] == ("919811122233", "hi *Wa Person*") and "not registered" in out[1][1]


def test_fast_path_period_and_routing():
    import datetime as _dt
    from app import fastpath as fp
    T = _dt.date(2026, 10, 27)
    assert fp.parse_period("oct", T) == (_dt.date(2026, 10, 1), T)
    assert fp.parse_period("september", T) == (_dt.date(2026, 9, 1), _dt.date(2026, 9, 30))
    assert fp.parse_period("nov", T) == (_dt.date(2025, 11, 1), _dt.date(2025, 11, 30))     # future month = last year
    assert fp.parse_period("for Oct 26", T) == (_dt.date(2026, 10, 26),) * 2
    assert fp.parse_period("26 oct", T) == (_dt.date(2026, 10, 26),) * 2
    assert fp.parse_period("1 oct to 15 oct", T) == (_dt.date(2026, 10, 1), _dt.date(2026, 10, 15))
    assert fp.parse_period("kal ka", T) == (_dt.date(2026, 10, 26),) * 2
    assert fp.parse_period("last month", T) == (_dt.date(2026, 9, 1), _dt.date(2026, 9, 30))
    assert fp.parse_period("hello", T) is None
    assert fp._division("show only seamless") == "U2" and fp._division("welded") == "U1"


def test_fast_path_runs_engine_without_ai(monkeypatch):
    import json as _json
    from sqlalchemy import text as _t
    from app import datadb
    with datadb.engine.begin() as c:
        c.execute(_t("DROP TABLE IF EXISTS VIEW_REJECTION_PBI"))
        c.execute(_t('CREATE TABLE VIEW_REJECTION_PBI (DIV_CODE TEXT, TNATURE TEXT, VRDATE TEXT, PLANT_CODE TEXT, '
                     'ITEM_GROUP_NAME TEXT, GODOWN_CODE TEXT, GODOWN_NAME TEXT, "Production Qty (MT)" REAL)'))
        c.execute(_t("INSERT INTO VIEW_REJECTION_PBI VALUES (:a,:b,:c,'P1','FG','OK','FG',:d)"),
                  [{"a": "U1", "b": "PROD", "c": "05-SEP-2026", "d": 80.0}, {"a": "U1", "b": "REJP", "c": "06-SEP-2026", "d": 20.0},
                   {"a": "U2", "b": "PROD", "c": "07-SEP-2026", "d": 50.0}, {"a": "U1", "b": "PROD", "c": "05-AUG-2026", "d": 90.0},
                   {"a": "U1", "b": "REJP", "c": "06-AUG-2026", "d": 10.0}])
    datadb.refresh_schema_cache()
    store.save_skill(_json.load(open("examples/skills/final_production_rejection_report.json")), changed_by="test")
    u = store.add_user("Fast Admin", "admin")

    def boom(*a, **k):
        raise AssertionError("the AI must not be called on the fast path")
    monkeypatch.setattr(agent.client.messages, "create", boom)
    monkeypatch.setattr(agent.client.messages, "stream", boom, raising=False)
    evs = []
    r = agent.handle_message(u, "/final-production-rejection-report september", "web", "fast1", emit=evs.append)
    assert "Final" in r.text and "SEP" in r.text.upper() and "Aug 2026" in r.text and "Rework **0" not in r.text, r.text
    assert r.kpis and any(f["format"] == "dashboard" for f in r.files) and not any(f["format"] == "pdf" for f in r.files)
    assert len(r.suggestions) >= 2
    assert any(e.get("type") == "figure" for e in evs)
    r2 = agent.handle_message(u, "rejection report sep", "web", "fast2")             # plain words work too
    assert r2.kpis
    r3 = agent.handle_message(u, "/final-production-rejection-report july 2026", "web", "fast3")
    assert r3.text.startswith("⚠️") and "VRDATE" in r3.text                          # empty month explained, no AI


def test_upload_and_attachment_tools(tmp_path):
    from openpyxl import Workbook
    from app import uploads
    wb = Workbook(); ws = wb.active; ws.title = "Data"
    ws.append(["Monthly dispatch"]); ws.append(["Plant", "Grade", "Qty MT"])
    for i in range(300):
        ws.append(["P1" if i % 3 else "P2", "304", 1.5])
    buf = tmp_path / "d.xlsx"; wb.save(buf)
    u = store.add_user("Uploader", "manager")
    from fastapi.testclient import TestClient
    from app.main import app
    store.set_login(u["id"], "uploader", "UploadPass123")
    with TestClient(app) as c:
        H = {"Authorization": "Bearer " + _login(c, "uploader", "UploadPass123").json()["token"]}
        r = c.post("/api/upload", headers=H, files={"file": ("dispatch.xlsx", buf.read_bytes())})
        assert r.status_code == 200, r.text
        meta = r.json()
        assert c.post("/api/upload", headers=H, files={"file": ("x.exe", b"MZ")}).status_code == 400
    s = meta["sheets"][0]
    assert meta["kind"] == "table" and s["rows"] == 300 and s["columns"] == ["Plant", "Grade", "Qty MT"]
    assert s["totals"]["Qty MT"]["sum"] == 450
    ctx = agent.Ctx(user=u, role=store.get_role("manager"), channel="web", chat_key="up", request_text="x")
    t = agent._tool_attachment_totals(ctx, meta["id"], ["Qty MT"], ["Plant"])
    assert t["grand_total"]["Qty MT"] == 450 and {r[0] for r in t["rows"]} == {"P1", "P2"}
    assert agent._tool_read_attachment(ctx, meta["id"], start=290)["rows"].__len__() == 10
    other = store.add_user("Other", "manager")
    assert "error" in agent._tool_read_attachment(agent.Ctx(user=other, role={}, channel="web", chat_key="o", request_text=""), meta["id"])
    blocks, notes = uploads.prompt_blocks(u, [meta["id"]])
    assert "file_id" in blocks[0]["text"] and "300 data rows" in blocks[0]["text"] and notes
    import pytest as _pt
    with _pt.raises(uploads.UploadError):
        uploads.save(u, "old.xls", b"x")


def test_attachment_reaches_the_model(monkeypatch, tmp_path):
    from types import SimpleNamespace as NS
    from app import uploads
    u = store.add_user("Attach Q", "manager")
    meta = uploads.save(u, "notes.csv", b"Plant,Qty\nP1,10\nP2,5\n")
    seen = {}

    def fake_create(**kw):
        seen["msgs"] = list(kw["messages"])
        return NS(content=[NS(type="text", text="P1 has 10, P2 has 5.")], stop_reason="end_turn")
    monkeypatch.setattr(agent.client.messages, "create", fake_create)
    r = agent.handle_message(u, "rejection report oct", "web", "attq", attachments=[meta["id"]])   # files skip the fast path
    last = seen["msgs"][-1]["content"]
    assert isinstance(last, list) and any("P1,10" in b.get("text", "") for b in last), last
    assert r.text.startswith("P1 has 10")
    hist = store.recent_messages("attq", 4)
    assert "notes.csv" in hist[0]["content"] and meta["id"] in hist[0]["content"]


def test_boss_greeting_for_admin():
    assert agent.small_talk({"name": "Shubham", "role": "admin", "username": "admin"}, "hello").startswith("Hello Boss")
    assert agent.small_talk({"name": "Shubham", "role": "admin", "username": "admin"}, "hi veronica kaise ho").startswith("Hello Boss")
    assert "Boss" not in agent.small_talk({"name": "Ravi C", "role": "accounts"}, "hello")
    assert "Boss" not in agent.small_talk({"name": "Bharat Prajapati", "role": "admin", "username": "bharpra"}, "hello")   # admin role but not the owner


def test_creator_answer():
    assert "Shubham Kakde" in agent.small_talk({"name": "Ravi", "role": "accounts"}, "who made you")
    assert "Shubham Kakde" in agent.small_talk({"name": "Ravi", "role": "accounts"}, "tumhe kisne banaya")


def test_user_themes_admin_and_me():
    from app import store
    store.init_db()
    u = store.add_user("Theme Tester", "admin")
    assert store.user_themes(store.get_user(u["id"])) == store.THEMES
    assert store.set_user_themes(u["id"], ["titan", "forge", "bogus"]) == ["forge", "titan"]
    assert store.user_themes(store.get_user(u["id"])) == ["forge", "titan"]
    store.set_user_themes(u["id"], [])
    assert store.get_user(u["id"])["themes"] is None
    v = store.add_user("Viewer Tester", "accounts")
    assert store.user_themes(store.get_user(v["id"])) == ["aurora"] and not store.is_power(store.get_user(v["id"]))


def test_dash_custom_range():
    from app import dash
    a, b, ym = dash.custom_range("2026-09-05", "2026-09-20")
    assert (a.isoformat(), b.isoformat(), ym) == ("2026-09-05", "2026-09-20", "2026-09")
    assert dash.custom_range("05-09-2026", "01-09-2026")[0].isoformat() == "2026-09-01"
    assert dash.custom_range("", "2026-09-20") is None
    import pytest
    with pytest.raises(ValueError):
        dash.custom_range("2019-01-01", "2026-01-01")


def test_rename_username():
    from app import store
    store.init_db()
    u = store.add_user("Rename Tester", "admin")
    store.set_login(u["id"], "renameme", "Password123")
    assert store.rename_username(u["id"], "RENTEST") == "rentest"
    assert store.authenticate("RENTEST", "Password123")["id"] == u["id"]


def test_scrap_line_lock():
    import json as _j
    from app import store, agent
    from app.engines import scrap_mis
    test_scrap_mis_engine()
    L = ["S_PIPE1_EXP1", "S_PIPE1_PEEL", "S_PIPE1_PIL", "S_PIPE2_PEEL3", "S_PIPE2_PIL", "S_PIERC", "S_PIER2", "S_OTH"]
    out = scrap_mis.run({"sql_template": _j.dumps({"engine": "scrap_mis"})}, "2026-10-01", "2026-10-31", ["*"], lines=L)
    shown = [r[0] for k, v in out["results"].items() if k != "excl" for r in v["rows"]]
    assert "BA" not in shown and "Welded" not in shown and "SMLS Pipe (PEEL)" in shown
    page = out["files"]["dashboard"].decode()
    assert '"S_PIPE1_PEEL"' in page and "VPT_LINES" in page
    u = store.add_user("Line Tester", "admin")
    store.set_user_scrap_lines(u["id"], L)
    role = agent.effective_role(store.get_user(u["id"]))
    assert role["line_lock"] == L and not role["free_query"]


def test_scrap_u1_lock_reads_shared_seamless_view():
    """Sandeep (U1 lock) - welded rows live in the seamless view; '!VIEW_SEAMLESS_*' must not break his Scrap MIS."""
    import json as _j
    from app.engines import scrap_mis
    test_scrap_mis_engine()
    allowed = ["*", "!VIEW_SEAMLESS_*", "!VIEW_M2M_PBI"]
    out = scrap_mis.run({"sql_template": _j.dumps({"engine": "scrap_mis"})}, "2026-10-01", "2026-10-31", allowed, division="U1")
    shown = [r[0] for k, v in out["results"].items() if k != "excl" for r in v["rows"]]
    assert not any(s.startswith("SMLS") or s in ("BA", "M2M") for s in shown), shown


def test_issue_engine_division_and_plant_lock():
    """Issue dashboard: VIEW_ISSUE_ENGINE_PBI rows -> KPIs; U2 + plant lock applied on the server."""
    import json as _j
    from sqlalchemy import text as _t
    from app import datadb, store, agent
    from app.engines import issue
    with datadb.engine.begin() as c:
        c.execute(_t("DROP TABLE IF EXISTS VIEW_ISSUE_ENGINE_PBI"))
        c.execute(_t("CREATE TABLE VIEW_ISSUE_ENGINE_PBI (VRDATE TEXT, VRNO TEXT, DEPT_NAME TEXT, PLANT_NAME TEXT, DIV_CODE TEXT, "
                     "ITEM_GROUP TEXT, ITEM_CODE TEXT, ITEM_NAME TEXT, UM TEXT, QTY_ISSUED REAL, RATE REAL, VAL_ISSUED REAL)"))
        for r in [("05-OCT-26", "I1", "MAINT", "SMLS PIPE", "U2", "SPARES", "A", "BOLT", "NOS", 10, 50, 500),
                  ("06-OCT-26", "I2", "PROD", "PIERCING", "U2", "OIL", "B", "OIL", "LTR", 5, 200, 1000),
                  ("07-OCT-26", "I3", "PROD", "WELDED MILL", "U1", "OIL", "B", "OIL", "LTR", 2, 200, 400),
                  ("07-SEP-26", "I0", "PROD", "SMLS PIPE", "U2", "OIL", "B", "OIL", "LTR", 1, 200, 200)]:
            c.execute(_t("INSERT INTO VIEW_ISSUE_ENGINE_PBI VALUES (" + ",".join(f":{i}" for i in range(len(r))) + ")"), {str(i): v for i, v in enumerate(r)})
    datadb.refresh_schema_cache()
    sk = {"sql_template": _j.dumps({"engine": "issue"})}
    out = issue.run(sk, "2026-10-01", "2026-10-31", ["*"])
    k = {c["label"]: c for c in out["kpis"]}
    assert k["Issue value"]["value"] == round(1900 / 1e5, 2) and k["Issue lines"]["value"] == 3
    page = out["files"]["dashboard"].decode()
    assert "start(rows" in page and "WELDED MILL" in page
    lk = issue.run(sk, "2026-10-01", "2026-10-31", ["*"], division="U2", plants=["SMLS PIPE"])
    page = lk["files"]["dashboard"].decode()
    assert "WELDED MILL" not in page and "PIERCING" not in page and "SMLS PIPE" in page
    assert lk["summary"]["lines"] == 1
    u = store.add_user("Plant Tester", "admin")
    assert store.set_user_issue_plants(u["id"], ["SMLS PIPE", " ", "PIERCING"]) == ["PIERCING", "SMLS PIPE"]
    role = agent.effective_role(store.get_user(u["id"]))
    assert role["plant_lock"] == ["PIERCING", "SMLS PIPE"] and not role["free_query"]
    store.set_user_issue_plants(u["id"], [])
    assert "plant_lock" not in agent.effective_role(store.get_user(u["id"]))


def test_dashboard_waits_for_unsynced_view():
    """A dashboard whose view is not in the replica yet: hidden for users, calm notice instead of an error."""
    import json as _json
    from fastapi.testclient import TestClient
    from sqlalchemy import text as _t
    from app import dash, datadb
    from app.main import app
    with datadb.engine.begin() as c:
        c.execute(_t("DROP TABLE IF EXISTS VIEW_ISSUE_ENGINE_PBI"))
    datadb.refresh_schema_cache()
    store.save_skill(_json.load(open("examples/skills/issue_dashboard.json")), changed_by="t")
    u = store.add_user("Mgmt Viewer", "viewer")
    k = dash.make_token(u["id"])
    with TestClient(app) as c:
        c.cookies.set("rb_sess", store.create_session(u["id"], 1))
        assert "/dash/issue?k=" not in c.get(f"/dash?k={k}").text
        r = c.get(f"/dash/issue?k={k}&go=1")
        assert r.status_code == 503 and "waiting for its first ERP data sync" in r.text and "Traceback" not in r.text


def test_sales_dispatch_dashboard_admin_manager_only():
    """Monthwise Sales Dispatch: invoice view -> page ingest(); only admin + manager roles see it."""
    import json as _json
    from sqlalchemy import text as _t
    from app import datadb, dash
    from app.engines import sale_dispatch as sd
    with datadb.engine.begin() as c:
        c.execute(_t("DROP TABLE IF EXISTS VIEW_SALE_INVOICE_PBI"))
        c.execute(_t("CREATE TABLE VIEW_SALE_INVOICE_PBI (SALE_BILL_DATE TEXT, CUSTOMER_NAME TEXT, DIVISION TEXT, ITEM_NAME TEXT, "
                     "DISPATCH_QTY_KG REAL, MATERIAL_VALUE REAL)"))
        c.execute(_t("INSERT INTO VIEW_SALE_INVOICE_PBI VALUES ('05-OCT-2026','ACME','U1','SS PIPE',2000,800000),"
                     "('06-SEP-2026','BETA','U2','SS TUBE',1000,450000),('06-SEP-2025','OLD','U2','SS TUBE',1000,450000)"))
    datadb.refresh_schema_cache()
    sk = store.save_skill(_json.load(open("examples/skills/sales_dispatch_dashboard.json")), changed_by="t")
    out = sd.run(sk, "2026-04-01", "2026-10-30", ["*"])
    k = {c["label"]: c["value"] for c in out["kpis"]}
    assert k["Dispatch"] == 3.0 and k["Invoice lines"] == 2 and abs(k["Sale value"] - 0.125) < 0.01
    assert "ingest(A" in out["files"]["dashboard"].decode()
    from app import store as st
    for role, ok in (("viewer", False), ("manager", True), ("admin", True)):
        u = st.add_user(f"RBAC {role}", role)
        assert st.skill_allowed(st.get_skill("sales_dispatch_dashboard"), st.get_user(u["id"])) is ok, role


def test_file_links_are_signed_and_expire():
    """/files/... needs a valid, unexpired signature - a guessed, edited or old link gets 403."""
    import time as _time
    from fastapi.testclient import TestClient
    from app import config, filelinks
    from app.main import app
    d = config.OUTPUT_DIR / "abc123testfolder"
    d.mkdir(parents=True, exist_ok=True)
    (d / "r.xlsx").write_bytes(b"x")
    good = filelinks.url("abc123testfolder", "r.xlsx").split(config.PUBLIC_BASE_URL, 1)[1]
    with TestClient(app) as c:
        assert c.get("/files/abc123testfolder/r.xlsx").status_code == 403
        assert c.get(good).status_code == 401                                # signed link alone: sign-in needed
        c.cookies.set("rb_sess", store.create_session(store.add_user("File Reader", "viewer")["id"], 1))
        assert c.get(good).status_code == 200
        assert c.get(good.replace("r.xlsx?", "x.xlsx?")).status_code in (403, 404)
        old = int(_time.time()) - 10
        assert c.get(f"/files/abc123testfolder/r.xlsx?e={old}&s={filelinks._sig('abc123testfolder', 'r.xlsx', old)}").status_code == 403


def test_access_denied_is_logged_and_admins_alerted(monkeypatch):
    """Anything outside a user's rights: polite refusal for them, security event + admin alert behind the scenes."""
    import json as _json
    from fastapi.testclient import TestClient
    from app import agent, dash, security, config
    from app.main import app
    sent = []
    monkeypatch.setattr(security, "_alert", lambda u, kind, detail, ch, req: sent.append((u.get("name"), kind)))
    monkeypatch.setattr(security, "threading", type("T", (), {"Thread": lambda target, args, daemon: type("X", (), {"start": lambda self: target(*args)})(),
                                                              "Lock": __import__("threading").Lock}))
    security._last.clear()
    store.save_skill(_json.load(open("examples/skills/sales_dispatch_dashboard.json")), changed_by="t")
    u = store.add_user("Nosy Viewer", "viewer")
    u = store.get_user(u["id"])
    ctx = agent.Ctx(user=u, role=agent.effective_role(u), channel="web", chat_key="t", request_text="show me sales dispatch")
    r = agent._tool_run_report_engine(ctx, "sales_dispatch_dashboard", "2026-10-01", "2026-10-30")
    assert "error" in r
    r = agent._tool_log_access_denied(ctx, "purchase orders", "viewer has no purchase views")
    assert r["logged"]
    try:
        dash.build(u, "sales-dispatch", None)
    except PermissionError:
        pass
    ev = store.list_security_events(1)
    kinds = [e["kind"] for e in ev if e["user_id"] == u["id"]]
    assert "report_blocked" in kinds and "data_outside_access" in kinds and "dashboard_blocked" in kinds
    assert any(e["request_text"] == "show me sales dispatch" for e in ev if e["user_id"] == u["id"])
    assert sent and sent[0] == ("Nosy Viewer", "report_blocked")
    assert len([s for s in sent if s[1] == "report_blocked"]) == 1          # throttled: one alert per user + kind
    tok = store.create_session(u["id"], 1)
    with TestClient(app) as c:
        assert c.get("/api/admin/security", headers={"Authorization": f"Bearer {tok}"}).status_code == 403
        assert c.get("/api/users", headers={"Authorization": f"Bearer {tok}"}).status_code == 403
        for _ in range(config.LOGIN_MAX_FAILS):
            c.post("/api/login", json={"username": "nosyguess", "password": "wrong-wrong"})
        assert c.post("/api/login", json={"username": "nosyguess", "password": "wrong-wrong"}).status_code == 429
    kinds = [e["kind"] for e in store.list_security_events(1)]
    assert "admin_blocked" in kinds and "login_locked" in kinds
    assert (config.BASE_DIR / "logs" / "security.log").exists()


def test_access_control_console_admin_only_and_audited():
    """Admin manages users, roles + views and report access from the screen; safety rules hold; every change audited."""
    import json as _json
    from fastapi.testclient import TestClient
    from app import main as _main
    from app.main import app
    _main._fails.clear()                                  # an earlier test locked the test client's IP on purpose
    a = store.add_user("Console Admin", "admin"); store.set_login(a["id"], "consoleadm", "AdminPass123")
    v = store.add_user("Console Viewer", "viewer"); store.set_login(v["id"], "consoleview", "ViewPass123")
    store.save_skill(_json.load(open("examples/skills/sales_dispatch_dashboard.json")), changed_by="t")
    with TestClient(app) as c:
        ta = c.post("/api/login", json={"username": "consoleadm", "password": "AdminPass123"}).json()["token"]
        tv = c.post("/api/login", json={"username": "consoleview", "password": "ViewPass123"}).json()["token"]
        H, HV = {"Authorization": f"Bearer {ta}"}, {"Authorization": f"Bearer {tv}"}
        assert c.get("/api/admin/rbac", headers=HV).status_code == 403
        d = c.get("/api/admin/rbac", headers=H).json()
        assert {"users", "roles", "skills", "views"} <= set(d) and any(r["name"] == "viewer" for r in d["roles"])
        r = c.post("/api/admin/rbac/roles", headers=H, json={"name": "purchase", "allowed_tables": ["VIEW_GRN_PBI"], "free_query": True})
        assert r.status_code == 200 and store.get_role("purchase")["allowed_tables"] == ["VIEW_GRN_PBI"]
        assert c.post(f"/api/admin/rbac/users/{v['id']}", headers=H, json={"role": "purchase", "email": "pv@venuspipes.com"}).status_code == 200
        u = store.get_user(v["id"]); assert u["role"] == "purchase" and u["email"] == "pv@venuspipes.com"
        assert c.get("/api/me", headers=HV).status_code == 401                 # role change signs them out
        assert c.post(f"/api/admin/rbac/users/{a['id']}", headers=H, json={"role": "viewer"}).status_code == 400   # not own admin
        assert c.post(f"/api/admin/rbac/users/{a['id']}", headers=H, json={"active": False}).status_code == 400
        assert c.delete("/api/admin/rbac/roles/purchase", headers=H).status_code == 400                 # still has a user
        assert c.post("/api/admin/rbac/skills/sales_dispatch_dashboard", headers=H, json={"roles": ["manager", "nonexistent"]}).json()["allowed_roles"] == ["manager"]
        assert c.post("/api/admin/rbac/users", headers=H, json={"name": "New Person", "role": "viewer", "username": "newp", "password": "short"}).status_code == 400
        assert c.post("/api/admin/rbac/users", headers=H, json={"name": "New Person", "role": "viewer", "username": "newperson", "password": "LongEnough1"}).status_code == 200
        assert c.post("/api/login", json={"username": "newperson", "password": "LongEnough1"}).status_code == 200
        assert c.post(f"/api/admin/rbac/users/{v['id']}", headers=H, json={"active": False}).status_code == 200
        assert not store.get_user(v["id"])["active"]
    kinds = [e for e in store.list_security_events(1) if e["kind"] == "rbac_change"]
    assert len(kinds) >= 5 and any("purchase" in e["detail"] for e in kinds)


def test_dashboard_libraries_served_locally():
    """Director's rule: pages must not load charts / fonts from the internet."""
    from fastapi.testclient import TestClient
    from app import main, vendor
    c = TestClient(main.app)
    r = c.get("/vendor/chart.umd.min.js")
    assert r.status_code == 200 and len(r.content) > 50_000
    assert c.get("/vendor/fonts/fonts.css").status_code == 200
    assert c.get("/vendor/../config.py").status_code == 404
    assert c.get("/vendor/x.py").status_code == 404
    page = vendor.localize('<script src="https://cdn.tailwindcss.com"></script>'
                           '<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.4/chart.umd.min.js"></script>'
                           '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
                           '<link href="https://fonts.googleapis.com/css2?family=Inter&display=swap" rel="stylesheet">')
    assert vendor.leftovers(page) == []
    assert "/vendor/tailwind.css" in page and "/vendor/chart.umd.min.js" in page
    import pathlib
    for f in pathlib.Path("app/templates/dashboards").glob("*.html"):
        assert vendor.leftovers(vendor.localize(f.read_text(encoding="utf-8"))) == [], f.name
    assert "googleapis" not in c.get("/").text


def test_times_are_india_time():
    """VERONICA's DB stores UTC; users and the AI must always see India time (GMT+05:30)."""
    from datetime import datetime
    from app import config as cfg
    assert cfg.ist(datetime(2026, 10, 30, 14, 59)) == "30-10-2026 20:29 IST"
    assert cfg.iso_local(datetime(2026, 10, 30, 18, 45)) == "2026-10-31T00:15:00+05:30"   # date rolls over too
    assert cfg.ist(None) == ""
    u = store.add_user("Clock User", "admin")
    store.save_report(user_id=u["id"], channel="web", skill_name="", title="Clock test", request_text="x",
                      sql_text="SELECT 1", row_count=1, files=[], summary="", data_preview=[])
    r = agent._tool_search_report_history(SimpleNamespace(user=u, role={"is_admin": True}), "Clock test")[0]
    assert r["created_at"].endswith(" IST")
    from fastapi.testclient import TestClient
    from app import main as _main
    store.set_login(u["id"], "clockuser", "ClockPass123"); _main._fails.clear()
    with TestClient(_main.app) as c:
        tok = c.post("/api/login", json={"username": "clockuser", "password": "ClockPass123"}).json()["token"]
        h = c.get("/api/history", headers={"Authorization": f"Bearer {tok}"}).json()
        assert h and h[0]["created_at"].endswith("+05:30")
    assert "GMT+05:30" in agent._system_prompt(SimpleNamespace(user=u, role={"name": "admin", "is_admin": True}, channel="web"))[1]["text"]



def test_shared_dashboard_link_needs_sign_in():
    """A dashboard link forwarded to someone is useless without VERONICA sign-in as that person (admins excepted)."""
    from fastapi.testclient import TestClient
    from app import dash, main as _main
    owner = store.add_user("Link Owner", "viewer"); store.set_login(owner["id"], "linkowner", "OwnerPass123")
    other = store.add_user("Link Other", "viewer")
    adm = store.add_user("Link Admin", "admin")
    k = dash.make_token(owner["id"])
    _main._fails.clear()
    with TestClient(_main.app) as c:
        r = c.get(f"/dash?k={k}")                                            # stranger with only the link
        assert r.status_code == 401 and "Sign in required" in r.text and "/?next=%2Fdash%3Fk%3D" in r.text
        c.cookies.set("rb_sess", store.create_session(other["id"], 1))       # signed in as someone else
        assert c.get(f"/dash?k={k}").status_code == 403
        ev = store.list_security_events(1)
        assert any(e["kind"] == "link_not_yours" and e["user_name"] == "Link Other" for e in ev)
        assert any(e["kind"] == "link_without_login" for e in ev)
        c.cookies.set("rb_sess", store.create_session(adm["id"], 1))         # admin may open any link
        assert c.get(f"/dash?k={k}").status_code == 200
        c.cookies.clear()
        lr = c.post("/api/login", json={"username": "linkowner", "password": "OwnerPass123"})
        assert "rb_sess" in lr.cookies and "httponly" in lr.headers["set-cookie"].lower()   # login sets the cookie
        assert c.get(f"/dash?k={k}").status_code == 200                      # the owner, signed in
        c.post("/api/logout", headers={"Authorization": f"Bearer {lr.json()['token']}"})
        c.cookies.clear()
        assert c.get(f"/dash?k={k}").status_code == 401                      # signed out again


def test_denied_reply_is_flagged_for_red_alert():
    """Outside-rights answers carry denied=True (web turns red + alert music) and a polite admin hint."""
    from app import agent
    from app.main import _reply_json
    u = store.add_user("Red Alert Viewer", "viewer")
    ctx = agent.Ctx(user=u, role=agent.effective_role(u), channel="web", chat_key="t", request_text="sales orders")
    out = agent._tool_log_access_denied(ctx, "sales orders", "not in role")
    assert ctx.reply.denied and "contact your admin" in out["say"]
    assert _reply_json(ctx.reply)["denied"] is True
    assert _reply_json(agent.AgentReply(text="ok"))["denied"] is False


def test_denied_message_never_explains():
    import re
    """Refusal is one fixed polite line in the user's language - no role, views or reason."""
    from app.agent import denied_message
    for q in ["show sales orders", "aaj ke sales order dikhao", "आज के सेल्स ऑर्डर दिखाओ", "આજના સેલ્સ ઓર્ડર બતાવો"]:
        m = denied_message(q)
        assert "admin" in m and not re.search(r"role|view|production|division|plant|शामिल", m, re.I)


def test_admin_controls_who_gets_security_alerts():
    """Admin switches security alert mails on/off per person (e.g. director); default = admins only."""
    from fastapi.testclient import TestClient
    from app import main as _main, security
    adm = store.add_user("Alert Admin", "admin"); store.set_login(adm["id"], "alertadm", "AlertPass123")
    director = store.add_user("Director Person", "manager"); store.set_user_contact(director["id"], email="dir@venuspipes.com")
    assert store.gets_security_alerts(store.get_user(adm["id"])) and not store.gets_security_alerts(store.get_user(director["id"]))
    _main._fails.clear()
    with TestClient(_main.app) as c:
        h = {"Authorization": "Bearer " + c.post("/api/login", json={"username": "alertadm", "password": "AlertPass123"}).json()["token"]}
        assert c.post(f"/api/admin/rbac/users/{director['id']}", headers=h, json={"alerts": True}).status_code == 200
        assert next(u for u in c.get("/api/admin/rbac", headers=h).json()["users"] if u["id"] == director["id"])["alerts"] is True
        assert c.post(f"/api/admin/rbac/users/{adm['id']}", headers=h, json={"alerts": False}).status_code == 200
    assert store.gets_security_alerts(store.get_user(director["id"]))
    assert not store.gets_security_alerts(store.get_user(adm["id"]))
    sent = []
    import app.outbox as ob
    orig, cfg = ob.send_email, security.config.SECURITY_ALERTS
    ob.send_email = lambda to, subj, body, paths: sent.append(to[0])
    security.config.SECURITY_ALERTS = ["email"]
    try:
        security._alert({"name": "Nosy", "role": "viewer"}, "report_blocked", "x", "web", "")
    finally:
        ob.send_email, security.config.SECURITY_ALERTS = orig, cfg
    assert "dir@venuspipes.com" in sent
    assert any(e["kind"] == "rbac_change" and "security alert mails ON" in e["detail"] for e in store.list_security_events(1))


def test_schema_in_prompt_and_answer_finishes_in_one_turn():
    """Speed: columns are in the system prompt; answer + KPI cards + follow-ups end the turn without another AI call."""
    from app import agent
    ctx = agent.Ctx(user=admin(), role=agent.effective_role(admin()), channel="web", chat_key="s1", request_text="x")
    sys_txt = "\n".join(b["text"] for b in agent._system_prompt(ctx))
    assert "DATABASE SCHEMA" in sys_txt and "invoices" in sys_txt and "amount" in sys_txt
    agent.client = FakeClaude([
        ([tool_use("run_sql", {"sql": "SELECT SUM(amount) AS total FROM invoices"}, 1)], "tool_use"),
        ([text("Total sales: 100"), tool_use("show_kpi_cards", {"kpis": [{"label": "Sales", "value": 100}]}, 2),
          tool_use("suggest_followups", {"items": ["Branch wise?", "Last month?"]}, 3)], "tool_use"),
    ])
    r = agent.handle_message(admin(), "total sales", "web", "speed1")
    assert len(agent.client.calls) == 2 and r.text.startswith("Total sales")
    assert r.kpis and r.kpis[0]["label"] == "Sales" and r.suggestions == ["Branch wise?", "Last month?"]


def test_master_files_are_searchable():
    """Admin drops an item master in knowledge/masters; VERONICA finds rows without querying the ERP."""
    from app import agent, masters
    d = masters.folder()
    d.mkdir(parents=True, exist_ok=True)
    f = d / "item_master_test.csv"
    f.write_text("Item Code,Description,Grade\nP-100,Seamless pipe 6in,TP316L\nP-200,Welded pipe 4in,TP304\n", encoding="utf-8")
    try:
        ctx = agent.Ctx(user=admin(), role=agent.effective_role(admin()), channel="web", chat_key="m", request_text="x")
        assert "item_master_test" in "\n".join(b["text"] for b in agent._system_prompt(ctx))
        out = agent._tool_lookup_master(ctx, "item_master_test", "seamless 316")
        assert out["matches"] == 1 and out["rows"][0]["Item Code"] == "P-100"
        assert "error" in agent._tool_lookup_master(ctx, "nope")
    finally:
        f.unlink()


def test_phone_keys_reach_only_my_own_screens():
    """Arc keyboard remote: a key sent from the phone is queued for the same user's open screens, nobody else's."""
    import asyncio
    from fastapi.testclient import TestClient
    from app import main
    c = TestClient(main.app)
    q_me, q_other = asyncio.Queue(), asyncio.Queue()
    me = admin()
    main._remote.clear()
    main._remote[me["id"]] = {q_me}
    main._remote[me["id"] + 999] = {q_other}
    sess = store.create_session(me["id"], 1)
    r = c.post("/api/remote/key", json={"k": "S", "src": "phone1"}, headers={"Authorization": "Bearer " + sess})
    assert r.status_code == 200 and r.json()["screens"] == 1
    assert q_me.get_nowait() == {"k": "S", "src": "phone1"} and q_other.empty()
    assert c.post("/api/remote/key", json={"k": "S"}).status_code == 401
    main._remote.clear()


def test_director_mis_reads_all_reports_together():
    """Director MIS runs every taught engine for the period and analyses them on one page (directors / admin only)."""
    import json as _json
    sk = _json.load(open("examples/skills/director_mis.json"))
    store.save_skill(sk, changed_by="test")
    ctx = agent.Ctx(user=admin(), role=agent.effective_role(admin()), channel="web", chat_key="dm", request_text="director mis oct")
    r = agent._tool_run_report_engine(ctx, "director_mis", "2026-10-01", "2026-10-31")
    assert "error" not in r, r
    areas = r["summary"]["areas"]
    read = [a for a, v in areas.items() if "not_available" not in v]
    assert len(read) >= 3, areas
    assert "dashboard" in r["files_created"]
    page = open(next(f for f in ctx.reply.files if f["format"] == "dashboard")["path"], encoding="utf-8").read()
    assert "Director MIS" in page and "Health by area" in page and "data-theme" in page
    from app import config as _cfg
    open(str(_cfg.OUTPUT_DIR / "director_mis_test.html"), "w", encoding="utf-8").write(page)
    from app.engines import director_mis as dm                                  # a division-locked user never sees
    so = next(x for x in dm.SUBS if x[1] == "sales_order")                     # an area that cannot be split by division
    if not store.get_skill(so[0]):
        store.save_skill(_json.load(open("examples/skills/sale_order_dashboard.json")), changed_by="test")
    locked = dm._run_one(so, "2026-10-01", "2026-10-31", ["*"], None, "U2")
    assert locked.get("hidden") and "not available for your access" in locked["error"]
    v = store.add_user("DM Viewer", "viewer")                                  # not a director -> no access
    vctx = agent.Ctx(user=v, role=agent.effective_role(v), channel="web", chat_key="dmv", request_text="director mis")
    assert "error" in agent._tool_run_report_engine(vctx, "director_mis", "2026-10-01", "2026-10-31")


def test_security_hardening_controls():
    """Each control proven both ways: the bad case is refused AND the good case still works."""
    from types import SimpleNamespace as NS
    from fastapi.testclient import TestClient
    from app import main, whatsapp, config
    # 1. proxy header believed only from this server (tunnel), not from a LAN caller
    lan = NS(client=NS(host="10.0.0.25"), headers={"cf-connecting-ip": "1.2.3.4"})
    tun = NS(client=NS(host="127.0.0.1"), headers={"cf-connecting-ip": "1.2.3.4"})
    assert main.client_ip(lan) == "10.0.0.25" and main.client_ip(tun) == "1.2.3.4"
    c = TestClient(main.app)
    # 2. service key cannot impersonate users while the chat bridge is off; works when it is on
    hdr = {"X-API-Key": "svc", "X-Telegram-Id": "111"}                       # the bootstrap admin's linked id
    old = config.TELEGRAM_ENABLED
    try:
        config.TELEGRAM_ENABLED = False
        assert c.get("/api/me", headers=hdr).status_code == 401
        config.TELEGRAM_ENABLED = True
        assert c.get("/api/me", headers=hdr).status_code == 200
    finally:
        config.TELEGRAM_ENABLED = old
    # 3. security headers on pages and APIs
    r = c.get("/health")
    assert r.headers["X-Frame-Options"] == "SAMEORIGIN" and r.headers["Referrer-Policy"] == "no-referrer"
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    # 4. WhatsApp webhook without an app secret is refused (cannot prove it is Meta); with the right signature it passes
    old_s = config.WHATSAPP_APP_SECRET
    try:
        config.WHATSAPP_APP_SECRET = ""
        assert not whatsapp.verify_signature(b"{}", "")
        config.WHATSAPP_APP_SECRET = "s3"
        import hashlib, hmac
        good = "sha256=" + hmac.new(b"s3", b"{}", hashlib.sha256).hexdigest()
        assert whatsapp.verify_signature(b"{}", good) and not whatsapp.verify_signature(b"{}", "sha256=bad")
    finally:
        config.WHATSAPP_APP_SECRET = old_s
    # 5. unknown login costs the same hashing as a wrong password (no username probing); right password still works
    import time as _t
    t0 = _t.time(); assert store.authenticate("no-such-user-x", "whatever") is None; miss = _t.time() - t0
    assert miss > 0.02                                                       # a PBKDF2 round was paid
    # 6. reports by e-mail only to company addresses
    old_d = config.MAIL_ALLOWED_DOMAINS
    from app import outbox
    old_ready = outbox.channel_ready
    outbox.channel_ready = lambda ch: ""                                      # mail "configured" for this check
    try:
        config.MAIL_ALLOWED_DOMAINS = ["venuspipes.com"]
        ctx = agent.Ctx(user=admin(), role=agent.effective_role(admin()), channel="web", chat_key="sec", request_text="send")
        ctx.reply.files = []
        rid = store.save_report(user_id=admin()["id"], channel="web", skill_name=None, title="T", request_text="t", sql_text="",
                                row_count=0, summary="", data_preview=[], files=[{"format": "excel", "filename": "a.xlsx",
                                "url": "", "path": __file__}])
        out = agent._tool_send_files(ctx, "email", ["someone@gmail.com"], report_id=rid)
        assert "error" in out and "company e-mail" in out["error"]
        out2 = agent._tool_send_files(ctx, "email", ["md@venuspipes.com"], report_id=rid)
        assert "error" not in out2 or "company e-mail" not in out2.get("error", "")
    finally:
        config.MAIL_ALLOWED_DOMAINS = old_d
        outbox.channel_ready = old_ready
