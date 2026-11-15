"""Who presents the HTTPS certificate for Meta / Anthropic from this PC? (read-only check)"""
import socket, ssl, datetime
from pathlib import Path
from cryptography import x509

out = []
for host in ("graph.facebook.com", "api.anthropic.com"):
    try:
        ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
        with socket.create_connection((host, 443), timeout=15) as s, ctx.wrap_socket(s, server_hostname=host) as t:
            c = x509.load_der_x509_certificate(t.getpeercert(binary_form=True))
        out.append(f"{host}\n  issuer : {c.issuer.rfc4514_string()}\n  subject: {c.subject.rfc4514_string()}")
    except Exception as e:
        out.append(f"{host}\n  ERROR {type(e).__name__}: {e}")
import os
out.append("proxy env: " + ", ".join(f"{k}={v}" for k, v in os.environ.items() if "proxy" in k.lower()) or "none")
Path(__file__).resolve().parent.parent.joinpath("logs", "tls_diag.txt").write_text(
    datetime.datetime.now().isoformat() + "\n" + "\n".join(out), encoding="utf-8")
