"""Build a sanitised, shareable copy of this project (no secrets, no company data).

    python -m tools.make_public ../veronica-ai-public

Leaves out: .env, logs, output, caches, the company's report engines, dashboard
templates, knowledge files, company skills and the company setup guide; replaces
company names, domains and database names with neutral ones. Check the result
before you push it - this is a safety net, not a guarantee."""
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", ".venv", "logs", "output", "__pycache__", ".pytest_cache", "node_modules"}
SKIP_FILES = {
    ".env", "tools/make_public.py", "tools/jobcard_scrap_verify.py", "tools/jobcard_scrap_sql.py",
    "app/engines/final_production.py", "app/engines/jobcard_scrap.py", "app/engines/scrap_mis.py",
    "app/engines/sales_order.py", "docs/VERONICA_Laptop_Setup_Guide.md",
    "examples/skills/final_production_rejection_report.json", "examples/skills/jobcardwise_scrap.json",
    "examples/skills/sale_order_dashboard.json", "examples/skills/scrap_mis_report.json",
}
SKIP_PREFIX = ("public/", "app/templates/dashboards/", "knowledge/", "docs/dashboard_recipes/")
SKIP_SUFFIX = (".db", ".pyc", ".log", ".bat", ".exe", ".mp3", ".zip", ".xlsx", ".pdf")
TEXT = {".py", ".md", ".json", ".html", ".js", ".css", ".txt", ".yml", ".yaml", ".toml", ".ps1", ".sh",
        ".sql", ".service", ".example", ".webmanifest", ".gitignore", ""}
REPLACE = [
    (r"Tie every insight to Venus Pipes' own\s+terms:[^\n]*", "Tie every insight to the company's own terms (see the knowledge files)."),
    (r"Venus Pipes (&|and|&amp;) Tubes", "Your Company"), (r"Venus Pipes", "Your Company"),
    (r"Venus reports", "company reports"), (r"\bVenus\b", "Your Company"),
    (r"venuspipes\.com", "example.com"), (r"venuserp_replica", "erp_replica"), (r"venuserp", "erp"),
    (r"Your Smart Partner in Pipes & Tubes", "Your smart reporting partner"),
    (r"Bharat Prajapati", "Asha Verma"), (r"Ravi Choudhary", "Neha Shah"), (r"Shubham Kakde", "the project author"), (r"\bBharat\b", "Asha"),
    (r"(?i)\b(view_[a-z0-9_]+?)_pbi\b", r"\1"), (r"venus123", "verify123"),
    (r"[\w.-]+\.trycloudflare\.com", "your-tunnel.trycloudflare.com"),
]
DROP_TESTS = ["test_final_production_engine_matches_dashboard_rules", "test_jobcard_scrap_engine_rules_and_dashboard",
              "test_live_dashboard_links", "test_scrap_mis_engine", "test_scrap_mis_welded_view",
              "test_scrap_mis_text_dates", "test_sales_order_engine"]   # need the company engines left out
DASH_EMPTY = '''DASHBOARDS = {
    # "url-name": ("skill name", "engine name", "Title", "subtitle"),  e.g.
    # "sales-order": ("sale_order_dashboard", "sales_order", "Sales Order MIS", "Order book - pending - late delivery"),
}
'''
LEAK = re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}|\d{8,10}:[A-Za-z0-9_-]{30,}|EAA[A-Za-z0-9]{40,}|venus|@venuspipes|"
                  r"1313103675230050|2902261706812642", re.I)


def main(dest: str) -> None:
    out = Path(dest).resolve()
    if out.exists():
        shutil.rmtree(out)
    n = 0
    for p in sorted(ROOT.rglob("*")):
        rel = p.relative_to(ROOT).as_posix()
        if p.is_dir() or set(p.relative_to(ROOT).parts) & SKIP_DIRS or rel in SKIP_FILES \
                or rel.startswith(SKIP_PREFIX) or rel.endswith(SKIP_SUFFIX):
            continue
        q = out / rel
        q.parent.mkdir(parents=True, exist_ok=True)
        if p.suffix in TEXT or p.name in (".gitignore", ".env.example", "Dockerfile"):
            s = p.read_text(encoding="utf-8", errors="replace")
            for a, b in REPLACE:
                s = re.sub(a, b, s)
            if rel == "app/dash.py":
                s = re.sub(r"DASHBOARDS = \{.*?\n\}\n", DASH_EMPTY, s, count=1, flags=re.S)
            if rel.startswith("tests/"):
                for t in DROP_TESTS:
                    s = re.sub(rf"\ndef {t}\(.*?(?=\ndef |\Z)", "\n", s, flags=re.S)
            q.write_text(s, encoding="utf-8")
        else:
            shutil.copy2(p, q)
        n += 1
    for p in sorted((ROOT / "public").rglob("*")):     # public/ overrides: README, LICENSE, docs/index.html ...
        if p.is_file():
            q = out / p.relative_to(ROOT / "public")
            q.parent.mkdir(parents=True, exist_ok=True)
            if q.name == "index.html" and "<!doctype" not in p.read_text(encoding="utf-8")[:200].lower():
                q.write_text('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
                             '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
                             '</head>\n<body>\n' + p.read_text(encoding="utf-8") + '\n</body>\n</html>\n', encoding="utf-8")
            else:
                shutil.copy2(p, q)
    leaks = [f"{f.relative_to(out)}: {m.group(0)[:12]}..." for f in out.rglob("*") if f.is_file() and f.suffix in TEXT
             for m in [LEAK.search(f.read_text(encoding="utf-8", errors="ignore"))] if m]
    print(f"{n} files -> {out}")
    print("possible leaks:\n  " + "\n  ".join(leaks) if leaks else "no secrets or company names found")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else str(ROOT.parent / "veronica-ai-public"))
