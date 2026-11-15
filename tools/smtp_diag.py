import socket, ssl, smtplib, sys, traceback
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config
HOST = config.SMTP_HOST or "smtp.office365.com"      # the company mail server from .env
out = []
for host, port in ((HOST, 465), (HOST, 587), (HOST, 25)):
    try:
        s = socket.create_connection((host, port), timeout=10)
        if port == 465:
            ctx = ssl.create_default_context(); t = ctx.wrap_socket(s, server_hostname=host)
            out.append(f"{port}: TCP ok, TLS ok, cert issuer={dict(x[0] for x in t.getpeercert()['issuer']).get('organizationName')}, banner={t.recv(200)!r}")
        else:
            s.settimeout(10); out.append(f"{port}: TCP ok, banner={s.recv(200)!r}")
        s.close()
    except Exception as e:
        out.append(f"{port}: FAILED {type(e).__name__}: {e}")
try:
    with smtplib.SMTP(HOST, 587, timeout=20) as c:
        c.ehlo(); c.starttls(); c.ehlo(); out.append("587 starttls ok")
except Exception as e:
    out.append(f"587 starttls: {type(e).__name__}: {e}")
open("logs/smtp_diag.txt", "w").write("\n".join(out)); print("\n".join(out))
