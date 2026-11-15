# Go live without Docker (Windows) + VERONICA voice

The result: `https://veronica.venuspipes.com` (or your own name) works from anywhere, starts by itself
when the PC boots, and VERONICA can listen and talk back in a warm female voice (Google Gemini).

> The PC must stay **on** (sleep off) for the site to work. For 24/7 use put it on an always-on office PC/server.

---

## 1. Stop the Docker version (only if it is running)
```
cd C:\reportbot
docker compose down
```
Then Docker Desktop can be closed / uninstalled. Your users, reports and skills are in MySQL - nothing is lost.

## 2. Install Python (one time)
Download **Python 3.12** from python.org/downloads/windows, run it, **tick "Add python.exe to PATH"**, Install.

## 3. Install ReportBot (one time)
Extract the new `reportbot.zip` over `C:\reportbot` (Replace all), then in PowerShell:
```
cd C:\reportbot
powershell -ExecutionPolicy Bypass -File deploy\windows\install.ps1
```
It creates `.venv`, installs packages, changes `host.docker.internal` to `127.0.0.1` in `.env`, and checks the database.

## 4. Voice key (Gemini)
1. Open **aistudio.google.com/apikey** with a Google account → **Create API key** → copy.
2. `notepad .env` → set `GEMINI_API_KEY=` (paste) → save.
3. Test the voice:
```
.venv\Scripts\python.exe -m tools.manage say "Namaste! Main Veronica hoon. Aaj main aapki kya madad kar sakti hoon?"
```
   Open `voice_test.mp3` and listen. Want a more Indian voice? List Google's female Hindi voices and put one name in `GEMINI_VOICE`:
```
.venv\Scripts\python.exe -m tools.manage voices hi-IN
```

## 5. Test locally
```
deploy\windows\start.bat
```
Open `http://localhost:8000`, sign in, tap **Talk to VERONICA**, speak. Close the window with Ctrl+C when done.

## 6. Start automatically at boot
PowerShell **as Administrator**:
```
powershell -ExecutionPolicy Bypass -File C:\reportbot\deploy\windows\install-autostart.ps1
```
After any `.env` change: `deploy\windows\restart.bat` (as Administrator). Logs: `C:\reportbot\logs\server.log`.

## 7. Permanent internet address (Cloudflare Tunnel - free)
Needs: a free Cloudflare account and your domain (`venuspipes.com`) using Cloudflare DNS (ask whoever manages the domain - one-time change of nameservers).
1. **dash.cloudflare.com → Zero Trust → Networks → Tunnels → Create a tunnel → Cloudflared**, name `reportbot`.
2. It shows an install command with a long **token** (`eyJh...`) - copy only the token.
3. **Public Hostname** tab: Subdomain `veronica`, Domain `venuspipes.com`, Service **HTTP** `localhost:8000` → Save.
4. PowerShell **as Administrator**:
```
powershell -ExecutionPolicy Bypass -File C:\reportbot\deploy\windows\setup-tunnel.ps1 -Token "eyJh...PASTE..."
```
5. `notepad .env` → `PUBLIC_BASE_URL=https://veronica.venuspipes.com` → save → `deploy\windows\restart.bat`
Done - the link never changes again, even after restarts. No ports are opened on your router.

*No domain on Cloudflare yet?* Keep using the quick tunnel for now (`.\cloudflared.exe tunnel --url http://localhost:8000`, link changes on every restart).

## 8. PDF reports (optional on Windows)
Excel, HTML, charts and chat tables always work. PDF needs GTK:
install **MSYS2** (msys2.org) → open "MSYS2 MINGW64" → `pacman -S mingw-w64-x86_64-pango` →
in `.env` add `WEASYPRINT_DLL_DIRECTORIES=C:\msys64\mingw64\bin` → restart.

---

## Using the voice
| Where | How |
|---|---|
| Web | **Talk to VERONICA** (or tap the glowing core) = hands-free conversation: speak, pause, she answers aloud, then listens again. **End talk** to stop. |
| Web | 🎙️ mic = ask once by voice. 🔊 = read every answer aloud. 🔊 Listen under any answer = replay. |
| Web | EN / हि / ગુ / म button = language hint (needed only for Marathi vs Hindi). |

Microphone needs **https** (your Cloudflare address) or `localhost`. Chrome, Edge, Android and iPhone Safari all work.
Claude still does all thinking and database work; Gemini is only the ears and the voice.

## Security checklist before sharing the link
- Everyone has a username + password (`tools.manage set-login ...`); `WEB_REQUIRE_PASSWORD=true`.
- Bot MySQL user is read-only on the ERP database.
- Change passwords/keys that were ever pasted in chat.
- Optional extra lock: Cloudflare Zero Trust → Access → Application for `veronica.venuspipes.com` → allow only emails ending `@venuspipes.com` (one-time code login before the site opens).


## Live talking (Gemini Live)
* Needs `GEMINI_API_KEY` in `.env`. Tap **Talk** to speak naturally. You can interrupt her mid-sentence.
* She answers small talk instantly. Any number goes to Claude on MySQL, and the KPI cards and tables appear in chat. The right-hand **Activity** panel shows each lookup and how long it took.
* If Talk shows "Live voice unavailable", set `LIVE_NONBLOCKING=false` and restart. To use the old voice mode, set `LIVE_ENABLED=false`.
