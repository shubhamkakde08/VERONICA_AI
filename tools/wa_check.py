"""WhatsApp diagnostics: subscribes this app to the WhatsApp account (needed to receive messages) and prints status.
Never prints the token."""
import json, httpx
from app import config
G = "https://graph.facebook.com/v20.0"
H = {"Authorization": f"Bearer {config.WHATSAPP_TOKEN}"}
WABA = "2902261706812642"
out = {}
def call(m, path, **kw):
    try:
        r = httpx.request(m, f"{G}/{path}", headers=H, timeout=30, **kw); return r.status_code, r.json()
    except Exception as e:
        return 0, str(e)
out["token_set"] = bool(config.WHATSAPP_TOKEN)
out["phone"] = call("GET", f"{config.WHATSAPP_PHONE_ID}?fields=display_phone_number,verified_name,code_verification_status,quality_rating")
out["subscribed_before"] = call("GET", f"{WABA}/subscribed_apps")
out["subscribe"] = call("POST", f"{WABA}/subscribed_apps")
out["subscribed_after"] = call("GET", f"{WABA}/subscribed_apps")
s = json.dumps(out, indent=1, default=str)
open("logs/wa_check.txt", "w", encoding="utf-8").write(s)
print(s)
