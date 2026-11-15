"""Step-by-step SMTP test with the .env settings (never prints the password)."""
import smtplib, sys
from email.message import EmailMessage
from app import config
to = sys.argv[1] if len(sys.argv) > 1 else "you@yourcompany.com"
log = [f"host={config.SMTP_HOST} port={config.SMTP_PORT} ssl={config.SMTP_SSL} user={config.SMTP_USER!r} from={config.SMTP_FROM!r} pw_len={len(config.SMTP_PASSWORD or '')}"]
try:
    c = smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, timeout=30, local_hostname="veronica.local") if config.SMTP_SSL else smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=30, local_hostname="veronica.local")
    log.append("connected"); c.ehlo()
    if not config.SMTP_SSL:
        c.starttls(); c.ehlo(); log.append("starttls ok")
    c.login(config.SMTP_USER, config.SMTP_PASSWORD); log.append("login ok")
    m = EmailMessage(); m["From"], m["To"], m["Subject"] = config.SMTP_FROM, to, "VERONICA test mail"
    m.set_content("Hello! E-mail from VERONICA works.\n\n- VERONICA AI")
    c.send_message(m); log.append(f"OK - sent to {to}"); c.quit()
except Exception as e:
    log.append(f"FAILED at this step: {type(e).__name__}: {e}")
open("logs/mail_test.txt", "w", encoding="utf-8").write("\n".join(log)); print("\n".join(log))
