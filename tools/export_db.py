"""LAPTOP: dump VERONICA's own database (reportbot) and the ERP replica (venuserp_replica) for the new server.
Uses the logins already in .env - nothing is typed, nothing is printed."""
import os, glob, subprocess, sys, time
from pathlib import Path
from sqlalchemy.engine import make_url
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import config

def mysqldump():
    pats = [r"C:\Program Files\MySQL\MySQL Server *\bin\mysqldump.exe", r"C:\Program Files\MySQL\MySQL Workbench *\mysqldump.exe",
            r"C:\Program Files (x86)\MySQL\*\bin\mysqldump.exe", r"C:\xampp\mysql\bin\mysqldump.exe"]
    for p in pats:
        for f in sorted(glob.glob(p), reverse=True):
            return f
    sys.exit("mysqldump.exe not found - install MySQL Shell/Server tools or tell Claude.")

out = Path(__file__).resolve().parents[1] / "deploy" / "server" / "db_export"
out.mkdir(parents=True, exist_ok=True)
exe = mysqldump()
print("Using", exe)
for name in ("BOT_DB_URL", "DATA_DB_URL"):
    u = make_url(getattr(config, name))
    f = out / f"{u.database}.sql"
    env = dict(os.environ, MYSQL_PWD=u.password or "")
    t = time.time()
    with open(f, "wb") as fh:
        r = subprocess.run([exe, f"-h{u.host}", f"-P{u.port or 3306}", f"-u{u.username}", "--single-transaction", "--quick",
                            "--no-tablespaces", "--set-gtid-purged=OFF", "--default-character-set=utf8mb4", u.database],
                           stdout=fh, stderr=subprocess.PIPE, env=env)
    err = r.stderr.decode(errors="ignore").strip()
    print(f"{u.database}: {'OK' if r.returncode == 0 else 'FAILED'}  {f.stat().st_size/1e6:.1f} MB  {time.time()-t:.0f}s  {err[:200]}")
print("Files in", out, "- copy the db_export folder to the server: C:\\VeronicaAI\\db_export")
