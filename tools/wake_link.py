"""NEW_LINK_NOW.bat helper: waits for the new free Cloudflare link, writes it to .env (PUBLIC_BASE_URL only).
Prints no secrets."""
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG, ENV = ROOT / "logs" / "tunnel.log", ROOT / ".env"
URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def main():
    global LOG
    import sys
    if len(sys.argv) > 1:                     # NEW_LINK_NOW.bat uses its own log file (the old tunnel may still hold tunnel.log)
        LOG = ROOT / sys.argv[1]
    url, ok = None, False
    for _ in range(90):                       # up to 90 s
        t = LOG.read_text(encoding="utf-8", errors="ignore") if LOG.exists() else ""
        m = URL.findall(t)
        url = m[-1] if m else None
        ok = "Registered tunnel connection" in t
        if url and ok:
            break
        time.sleep(1)
    if not url:
        print("NO LINK: the tunnel did not start (no internet? check logs\\tunnel.log)")
        sys.exit(1)
    print("new link:", url, "(connected)" if ok else "(not confirmed yet)")
    lines = ENV.read_text(encoding="utf-8").splitlines()
    done = False
    for i, ln in enumerate(lines):
        if ln.startswith("PUBLIC_BASE_URL="):
            lines[i] = "PUBLIC_BASE_URL=" + url
            done = True
    if not done:
        lines.append("PUBLIC_BASE_URL=" + url)
    ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(".env PUBLIC_BASE_URL updated")
    whatsapp(url, lines)


def whatsapp(url: str, lines: list[str]):
    """Point Meta's WhatsApp webhook at the new link too (needs WHATSAPP_APP_ID + WHATSAPP_APP_SECRET in .env)."""
    env = {}
    for ln in lines:
        if "=" in ln and not ln.lstrip().startswith("#"):
            k, v = ln.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    app_id, secret, verify = env.get("WHATSAPP_APP_ID"), env.get("WHATSAPP_APP_SECRET"), env.get("WHATSAPP_VERIFY_TOKEN")
    if not (app_id and secret and verify):
        print("WhatsApp: WHATSAPP_APP_ID not set - update the callback URL in Meta by hand: " + url + "/whatsapp/webhook")
        return
    try:
        import sys
        sys.path.insert(0, str(ROOT))
        import httpx
        from app.net import TLS
        r = httpx.post(f"https://graph.facebook.com/v20.0/{app_id}/subscriptions", timeout=60, verify=TLS,
                       data={"object": "whatsapp_business_account", "callback_url": url + "/whatsapp/webhook",
                             "verify_token": verify, "fields": "messages", "access_token": f"{app_id}|{secret}"})
        print("WhatsApp webhook ->", url + "/whatsapp/webhook", ":", "OK" if r.status_code == 200 and r.json().get("success") else f"FAILED {r.status_code} {r.text[:200]}")
    except Exception as e:
        print("WhatsApp webhook update failed:", str(e)[:200])


if __name__ == "__main__":
    main()
