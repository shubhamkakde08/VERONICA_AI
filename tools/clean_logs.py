"""Run while VERONICA is stopped (RESTART_VERONICA.bat does it): masks old bot tokens in logs/*.log and *.txt.
Prints only counts, never the secrets."""
import re
from pathlib import Path

PAT = re.compile(rb"bot([0-9]{6,}):([A-Za-z0-9_-]{20,})|\b[0-9]{8,10}:AA[A-Za-z0-9_-]{30,}")
total = 0
for p in list(Path("logs").glob("*.log*")) + list(Path("logs").glob("*.txt")):
    try:
        data = p.read_bytes()
        new, n = PAT.subn(b"<token removed>", data)
        if n:
            p.write_bytes(new)
            total += n
            print(f"{p.name}: {n} token(s) masked")
    except OSError as e:
        print(f"{p.name}: skipped ({e.__class__.__name__})")
print(f"done - {total} masked")
