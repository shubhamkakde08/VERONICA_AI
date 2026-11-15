"""TLS for outgoing calls (Meta / WhatsApp, Telegram, Google voice).

httpx normally trusts only its own certificate list (certifi). Office networks and antivirus tools that inspect
HTTPS present their own certificate, which Windows trusts but certifi does not -> CERTIFICATE_VERIFY_FAILED.
This context trusts BOTH: the Windows / system certificate store and certifi. Verification stays on."""
import ssl

try:
    import truststore                                  # optional, if installed: the full OS trust logic
    TLS = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
except Exception:
    TLS = ssl.create_default_context()                 # on Windows this loads the system certificate store
    try:
        import certifi
        TLS.load_verify_locations(certifi.where())
    except Exception:
        pass
