# VERONICA AI – Laptop Setup Guide (do it yourself)

Run VERONICA on your laptop and let users reach it **from anywhere** (office WiFi, home, mobile data) through a free Cloudflare link, add **users**, and test everything.

> **Never** paste passwords, tokens or API keys in any chat. Keep them only in `C:\reportbot\.env`.

---

## 0. Before you start (once)

| Check | How |
|---|---|
| Bot installed in `C:\reportbot` | folder exists, has `.env` and `.venv` |
| MySQL running | `Get-Service *mysql*` → **Running** |
| Data synced | sync script ran today (or the **OracleSync** task is on) |
| Laptop won't sleep while plugged in | see step 7 |

Open **2 PowerShell windows as Administrator** (Start → type *PowerShell* → right-click → *Run as administrator*):

- **Window 1 = tunnel** (the public link). Keep it open the whole time.
- **Window 2 = commands**.

---

## 1. Start the bot (Window 2)

```powershell
cd C:\reportbot
Start-ScheduledTask ReportBot
Start-Sleep 15
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/health
```

✅ You should see `ok`.

❌ "task does not exist" → start it by hand and keep that window open:

```powershell
C:\reportbot\deploy\windows\start.bat
```

Want auto-start for next time (once)?

```powershell
powershell -ExecutionPolicy Bypass -File C:\reportbot\deploy\windows\install-autostart.ps1
```

---

## 2. Create the public link (Window 1)

This makes VERONICA reachable **outside your network** (any phone or PC with internet).

```powershell
C:\cloudflared\cloudflared.exe tunnel --url http://localhost:8000
```

- If not found, try `C:\reportbot\cloudflared.exe tunnel --url http://localhost:8000`.
- If cloudflared is missing, download it once:

```powershell
mkdir C:\cloudflared -Force
Invoke-WebRequest -UseBasicParsing https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe -OutFile C:\cloudflared\cloudflared.exe
```

Wait for a box like this, then copy the link:

```
https://something-random.trycloudflare.com
```

⚠️ **Do not close Window 1.** Closing it, or restarting the laptop, kills the link.

---

## 3. Tell VERONICA its link (Window 2)

```powershell
notepad C:\reportbot\.env
```

Change this one line to your new link, then save:

```
PUBLIC_BASE_URL=https://something-random.trycloudflare.com
```

Restart the bot:

```powershell
cd C:\reportbot
Stop-ScheduledTask ReportBot; Start-Sleep 5; Start-ScheduledTask ReportBot; Start-Sleep 15
```

**Test from outside:** phone with **WiFi OFF (mobile data)** → open the link → login page appears.

---

## 4. Your own admin login

**Web:** open the link → log in with your admin username and password.
Forgot it? Reset it:

```powershell
.venv\Scripts\python -m tools.manage users
.venv\Scripts\python -m tools.manage set-login 1 admin YourNewStrongPass
```

(`1` = your id from the `users` list.)

---

## 5. Add a user (viewer / manager / admin)

**Roles**

| Role | Can do |
|---|---|
| **viewer** | Ask questions, run taught reports, open dashboards. Cannot teach or schedule. No private views. |
| **manager** | Viewer + teach new reports + schedules. No private views. |
| **admin** | Everything, incl. private views (employee master) and adding users. |

Easiest: **Admin Console** (🛡 Admin, top right) → **Users** → **＋ New user**. Or from the command line:

```powershell
cd C:\reportbot
.venv\Scripts\python -m tools.manage add-user "Dwarika Gupta" viewer dwarika Dw@rika2026x
```

Format: `add-user "Full Name" <viewer|manager|admin> <username> <password>`


**Then** – send them privately (WhatsApp/SMS, one person at a time):

> VERONICA link: https://… (current link)
> Username: dwarika · Password: (theirs)
> After login: Account → Change password.

**Manage users**

```powershell
.venv\Scripts\python -m tools.manage users                   # list everyone
.venv\Scripts\python -m tools.manage set-login 5 dwarika NewPass2026   # reset password of user #5
.venv\Scripts\python -m tools.manage disable 5               # block user #5 (logs them out)
.venv\Scripts\python -m tools.manage enable 5                # unblock
```

### 5b. Department access (Production / Purchase / Sales / Accounts …)

Create the department roles once:

```powershell
.venv\Scripts\python -m tools.manage dept-roles
.venv\Scripts\python -m tools.manage roles
```

| Role | Sees |
|---|---|
| production | production, tubing, LSAW, slitting, welding, scrap, rejection, job-card scrap |
| quality | rejection / final inspection, scrap, weld conditions |
| purchase | purchase orders, GRN, stock ledger |
| stores | GRN, stock ledger |
| sales | sales orders, invoices, quotations |
| accounts | every report (employee master stays private) |
| admin | everything |

Add users with their department as the role:

```powershell
.venv\Scripts\python -m tools.manage add-user "Bharat Prajapati" production 111111111
.venv\Scripts\python -m tools.manage add-user "Ravi" accounts 222222222
.venv\Scripts\python -m tools.manage add-user "Rajesh" purchase 333333333
```

- Outside their department she says "This data is not in your access. Please contact your admin." 🔒
- They only see the reports and dashboards of their department.
- Change department: `set-role <id> sales` (or Admin Console → Users).
- Custom role: `add-role maintenance "VIEW_WELD_COND_PBI,VIEW_SCRAP_*" "Maintenance"` (`*` = any letters).
- Mixed access (role names expand): `add-role prod_stock "production,VIEW_ITEM_LEDGER_PBI"` then `set-role <id> prod_stock`.

---

## 6. Test checklist

Do these as the **viewer** (phone on mobile data):

| # | Test | Expected |
|---|---|---|
| 1 | Open link, log in | Greeting: "Good morning … How may I help you today?" |
| 2 | `/final-production-rejection-report oct` | KPI cards + tables + Excel + 🖥️ dashboard |
| 3 | `/jobcardwise-scrap%-report oct` | KPI cards + bucket tables + 🖥️ dashboard |
| 4 | Click the Excel file | It downloads |
| 5 | `employee list do` | "private, contact admin" 🔒 |
| 6 | No "＋ Teach a report" in Reports | viewers cannot teach |
| 7 | Mic → speak Hindi | She answers in Hindi, female voice |
| 8 | Esc / Stop while she speaks | She stops |
| 9 | Dashboards → open one | Live dashboard opens |
| 10 | Switch **Aurora / Arc** (top right) | Look changes |
| 11 | ⤢ / ▣ / — buttons in chat | Maximise / floating window / minimise |

---

## 7. Keep the laptop awake

```powershell
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
```

Lid: Control Panel → Power Options → *Choose what closing the lid does* → **Plugged in = Do nothing**. Keep the charger plugged in.

---

## 8. Every next time (after a restart)

The free link changes every time. Repeat:

1. Window 2: `Start-ScheduledTask ReportBot` (skip if auto-start is on).
2. Window 1: `C:\cloudflared\cloudflared.exe tunnel --url http://localhost:8000` → copy the new link.
3. Put the new link in `.env` (`PUBLIC_BASE_URL=`) and restart the bot (or just run `NEW_LINK_NOW.bat`).
4. Send users the **new** link.

➡️ To stop the link changing, use the **permanent setup** (own domain + Cloudflare tunnel service). See section 10.

---

## 9. Problems

| Problem | Fix |
|---|---|
| `/health` gives an error | Bot not running → step 1; check `C:\reportbot\logs\server.log` (last 30 lines) |
| Link shows Cloudflare **Error 1033** | Window 1 closed → step 2 again |
| Link shows **Error 502** | Bot not running → step 1 |
| Login "locked" | Wait 15 min, or `set-login <id> <username> <newpassword>` |
| Excel/dashboard link doesn't open | Ctrl+F5 on the page; links always use the address you opened |
| Office WiFi blocks the link | Ask IT to allow `*.trycloudflare.com` (or your own domain later) |
| Old screen after update | Ctrl+F5 |

---

## 10. Later: permanent link (office PC)

1. Buy a domain (e.g. `veronica-venus.in`) → add it to a free Cloudflare account (change nameservers).
2. Cloudflare → Zero Trust → Networks → Tunnels → Create → copy the **token** → Public hostname `app.<domain>` → `http://localhost:8000`.
3. PowerShell (admin):

```powershell
powershell -ExecutionPolicy Bypass -File C:\reportbot\deploy\windows\setup-tunnel.ps1 -Token "PASTE_TOKEN"
```

4. `.env`: `PUBLIC_BASE_URL=https://app.<domain>` → restart → `set-webhook`.
5. Moving to the office PC: install the bot there, run the **same** `setup-tunnel.ps1` with the **same token**, then on the laptop run `C:\reportbot\cloudflared.exe service uninstall`. Same link, nothing changes for users.


---

## 11. Send reports by voice / text (e-mail · WhatsApp)

Say or type: "send this to Bharat on WhatsApp", "Ravi ko mail kar do", "mujhe mail karo".
VERONICA reads back what goes to whom and asks "Shall I send?" - nothing goes out before you say yes.
She skips anyone whose role cannot see that report.

### 11A. Save each person's e-mail / WhatsApp number (once)
```powershell
cd C:\reportbot
.venv\Scripts\python -m tools.manage users
.venv\Scripts\python -m tools.manage set-contact 12 user@yourcompany.com 9876543210
```
(12 = the person's # from `users`. Mobile without +91 is fine.)

### 11B. E-mail - company mail only

Company policy (31-Oct-2026): VERONICA sends mail only from the company domain (@venuspipes.com). Personal or free mail accounts are not allowed.

**Company mail (@venuspipes.com)** - ask the mail/IT vendor for: SMTP server, port, user, password, "is SMTP login allowed".
   - Microsoft 365 / Outlook: `SMTP_HOST=smtp.office365.com`, `SMTP_PORT=587`. Microsoft is switching off password-based SMTP
     during 2026 - if it says "authentication unsuccessful", ask IT for an SMTP relay or Option 3.
   - Other hosts (cPanel, Zoho, Rediff, GoDaddy): use the values they give; port 465 -> also add `SMTP_SSL=true`.

**Option 3 - Brevo (free 300 mails/day, sends as @venuspipes.com)**: brevo.com -> sign up -> SMTP & API -> SMTP -> copy server
   `smtp-relay.brevo.com`, port 587, login and SMTP key -> put in `.env` like above (SMTP_FROM = a sender you verified in Brevo).

5. Restart and test:
```powershell
Stop-ScheduledTask ReportBot; Start-Sleep 5; Start-ScheduledTask ReportBot
```
   In VERONICA: run any report -> "mail this to me" -> yes. (Save your own e-mail first with set-contact.)

### 11C. WhatsApp (Meta WhatsApp Cloud API)

You need: a Facebook account, a **mobile number NOT used on WhatsApp / WhatsApp Business app** (new SIM is best), company details.
Charges: Meta bills per message for template messages (see Meta's WhatsApp pricing page); replies inside the 24-hour window are free.

1. **Developer account** - open https://developers.facebook.com -> log in with Facebook -> **Get started** -> verify phone/e-mail.
2. **Create app** - My Apps -> **Create app** -> name `VERONICA` -> use case **"Connect with customers through WhatsApp"**
   -> select / create your **Business portfolio** (Venus Pipes) -> Create.
3. **Test first (5 min)** - left menu **WhatsApp -> API Setup**:
   - You get a free **test number**, a **temporary access token** (valid 24 h) and the **Phone number ID**.
   - Under "To", add your own mobile -> enter the OTP WhatsApp sends you.
   - `.env`:
```
WHATSAPP_TOKEN=(temporary access token)
WHATSAPP_PHONE_ID=(Phone number ID)
```
   - Restart bot. On your phone open WhatsApp, send **hi** to the test number. In VERONICA: "WhatsApp this to me" -> yes. ✅ file arrives.
4. **Real number (for everyone)** - API Setup -> **Add phone number** -> display name "VERONICA - Venus Pipes" -> verify by SMS/call.
   Copy its new **Phone number ID** into `.env`.
5. **Business verification** - business.facebook.com -> Settings -> Security Centre -> **Start verification** (GST / company docs).
   Needed to message more people and to get approved templates. Takes 1-5 days.
6. **Permanent token** (temporary one dies in 24 h) - business.facebook.com -> Settings -> **Users -> System users** -> Add
   (`veronica-bot`, Admin) -> **Assign assets**: your app (full control) + your WhatsApp account -> **Generate token** -> app VERONICA,
   expiry **Never**, tick `whatsapp_business_messaging` + `whatsapp_business_management` -> copy into `WHATSAPP_TOKEN=`.
7. **Payment** - WhatsApp Manager -> Payment settings -> add a card (needed for business-started messages).
8. **24-hour rule** - WhatsApp lets a business send freely only for 24 h after the person writes to it. Easiest: ask each HOD to send
   **hi** to the VERONICA number each morning (or once before you send). For sending any time: WhatsApp Manager -> **Message templates**
   -> Create -> Category *Utility* -> name `report_ready` -> text "Your VERONICA report is ready." -> submit (approval ~minutes-24 h)
   -> `.env`: `WHATSAPP_TEMPLATE=report_ready`.
9. Restart bot -> "Bharat ko WhatsApp pe bhejo" -> yes.

### 11D. WhatsApp webhook (users chat with VERONICA on WhatsApp + "hi" opens the 24 h window)
1. `.env`: `WHATSAPP_VERIFY_TOKEN=venus-veronica-2026` (any secret word) and `WHATSAPP_APP_SECRET=` (Meta app -> App settings -> Basic -> App secret -> Show) -> restart bot.
2. developers.facebook.com -> VERONICA app -> WhatsApp -> **Configuration** -> Webhook -> **Edit**:
   Callback URL `https://<your link>/whatsapp/webhook` · Verify token = the same word -> **Verify and save**.
3. Webhook fields -> **messages** -> **Subscribe**.
4. Test: WhatsApp "hi" to the VERONICA number -> she answers. Unknown numbers get their number to send to the admin (`set-contact`).
5. Link changed (free tunnel)? Edit the Callback URL again with the new link.

### Problems
| Message | Fix |
|---|---|
| "e-mail is not set up" | SMTP lines missing in `.env` or bot not restarted |
| "authentication unsuccessful / 535" | wrong password, or SMTP login not allowed on the company mailbox - ask the mail vendor / IT |
| "WhatsApp is not set up" | WHATSAPP_TOKEN / WHATSAPP_PHONE_ID missing |
| "only delivers to people who messaged … 24 h" | the person sends "hi" to the VERONICA number, or set WHATSAPP_TEMPLATE |
| WhatsApp error 190 | token expired -> make the permanent token (step 6) |
| "<name> has no whatsapp contact saved" | `set-contact <id> <email> <mobile>` |
| "files over 20 MB" | send only excel, or set `SEND_MAX_MB=40` in `.env` |
