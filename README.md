# VERONICA AI — Reporting Assistant   (Oracle DB + Python + MySQL + Claude)

<img width="1917" height="1061" alt="Screenshot 2026-10-28 174715" src="https://github.com/user-attachments/assets/35f587a4-e188-4738-ab7e-2156eee547ee" />





Managers ask in **English, हिंदी, ગુજરાતી or मराठी** (native script or Hinglish) and get answers from the ERP as
**chat tables, Excel, PDF, charts, HTML and live dashboards** — only within the access their role allows.
Company report formats are taught once and run forever as `/commands`.




https://github.com/user-attachments/assets/137c4c6e-ee48-40a8-a191-dde6c1668914



```
 Web app (chat · dashboards · Admin Console) ─► FastAPI ─► Claude agent ─┬─► MySQL copy of the ERP (read-only)
                                                   │                      └─► Report engines ─► Excel · PDF · Chart · HTML · Dashboards
                                                   ├─► Scheduler ─► company e-mail
                                                   └─► Security log (access denied, rights changes)
 Bot DB: users / roles · skills (versioned) · report history · schedules · security events
```

## Install on a new PC (Windows, about 15 minutes)

1. **Python 3.12+** from python.org → tick **"Add python.exe to PATH"** → Install. Also install **MySQL 8**.
2. **Get the code:** green **Code** button on GitHub → **Download ZIP** → extract to `C:\VeronicaAI`
   (or `git clone <this repo URL> C:\VeronicaAI`).
3. **Settings:** copy `.env.example` to `.env` and fill in your own values. You need at least:
   `ANTHROPIC_API_KEY`, `DATA_DB_URL` (read-only user on your ERP copy), `BOT_DB_URL`, `PUBLIC_BASE_URL`.
   Create the two MySQL users with the SQL under **MySQL users** below.
4. **Install + auto-start** (PowerShell as Administrator):
   ```
   cd C:\VeronicaAI
   powershell -ExecutionPolicy Bypass -File deploy\windows\install.ps1
   powershell -ExecutionPolicy Bypass -File deploy\windows\install-autostart.ps1
   ```
5. Open **http://127.0.0.1:8000** and sign in with the admin from `.env` (`BOOTSTRAP_ADMIN_NAME`).
   Optional: copy `knowledge/people.md.example` to `knowledge/people.md` (your team), and add the offline voice
   (`models/kokoro/README.md`).

> **Not in this repo on purpose:** `.env` (keys and passwords), user lists, `knowledge/people.md`, ERP data dumps,
> logs and generated reports. Never commit them - `.gitignore` already blocks them.

## What it does

| Feature | How |
|---|---|
| **Ask** | *"kal ka dispatch excel me do"*, *"is mahine top 10 customers kaun hai?"* — read-only SQL on the ERP copy |
| **Teach a report** | `/teach` — VERONICA interviews you (purpose, rules, columns, totals, formats), tests the SQL and saves it as `/your_report` |
| **Live dashboards** | Scrap MIS, Final Production / Rejection, Jobcard Scrap, Sales Order MIS, Issue / Costing, Monthwise Sales Dispatch |
| **Formats** | Chat table · Excel (₹ lakh/crore) · PDF · chart · HTML · dashboard; Indian number format, India time (IST) |
| **Access control** | Admin Console (🛡 Admin, top right): users, roles + ERP views, report access, division (U1/U2) and plant locks, looks, who gets security alerts |
| **Security** | Read-only DB user + SQL guard; dashboard / file links work only in a signed-in browser; every refused request logged; polite "not in your access" reply |
| **Offline-friendly** | Chart, Excel and font libraries served from this server — no CDN |
| **Voice** | Indian female voice (Gemini) with an offline backup voice |

## Run on Windows (no Docker)
See **[DEPLOY_WINDOWS.md](DEPLOY_WINDOWS.md)** and **docs/VERONICA_Laptop_Setup_Guide.md**: install, auto-start, restart
(`RESTART_VERONICA.bat`), public link, company mail, WhatsApp.

Quick start:
```bash
cp .env.example .env        # DB URLs, ANTHROPIC_API_KEY, PUBLIC_BASE_URL, company SMTP
pip install -r requirements.txt
python -m tools.manage init           # first admin
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### MySQL users
```sql
CREATE USER 'reportbot_ro'@'%' IDENTIFIED BY 'strong-password';
GRANT SELECT ON your_erp_db.* TO 'reportbot_ro'@'%';          -- ERP data: read-only
CREATE DATABASE reportbot CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'reportbot_rw'@'%' IDENTIFIED BY 'another-password';
GRANT ALL ON reportbot.* TO 'reportbot_rw'@'%';               -- VERONICA's own tables
```

## API (web app / other internal systems)
Auth: `Authorization: Bearer <session token from /api/login>` (or `X-API-Key: <SERVICE_API_KEY>` for system calls).

| Method | Path | |
|---|---|---|
| POST | `/api/login`, `/api/logout` | sign in / out (sets the secure session cookie) |
| POST | `/api/chat/stream` | ask VERONICA (streamed answer, tables, files) |
| GET | `/api/history?q=&skill=` | past reports |
| POST | `/api/dash-link` | personal dashboard link |
| GET | `/api/admin/rbac`, `/api/admin/security` | Admin Console data (admins only) |

## Files
```
app/agent.py       Claude agent: tools, system prompt (languages, Indian FY, access rules)
app/engines/       dashboard engines (one per report)
app/datadb.py      read-only MySQL access + SQL guard + schema discovery
app/store.py       users, roles, skills (+versions), reports, schedules, security events
app/security.py    access-denied log + alerts       app/vendor.py  local libraries instead of CDN
app/main.py        FastAPI routes                    app/static/_parts/  web app (build: python -m tools.build_ui)
knowledge/         report routes and business rules   examples/skills/  report skills   tests/  pytest suite
```
Run tests (no keys needed — fake Claude + sample SQLite ERP): `python -m pytest -q tests/`
