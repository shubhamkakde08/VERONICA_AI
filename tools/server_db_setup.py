"""SERVER: create VERONICA's MySQL databases + logins, then load the dumps copied from the laptop.
You type the MySQL root password (hidden). VERONICA's own password is read from .env. Nothing is printed."""
import getpass, glob, os, subprocess, sys
from pathlib import Path
import pymysql
from sqlalchemy.engine import make_url
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import config

bot, data = make_url(config.BOT_DB_URL), make_url(config.DATA_DB_URL)
host, port = bot.host or "127.0.0.1", bot.port or 3306
rootpw = getpass.getpass(f"MySQL root password on {host}:{port} (typing is hidden): ")
c = pymysql.connect(host=host, port=port, user="root", password=rootpw, autocommit=True)
cur = c.cursor()
def q(sql, *a):
    cur.execute(sql, a)
for db in {bot.database, data.database}:
    q(f"CREATE DATABASE IF NOT EXISTS `{db}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
for user in {bot.username, data.username}:
    q("CREATE USER IF NOT EXISTS %s@'localhost' IDENTIFIED BY %s", user, bot.password if user == bot.username else data.password)
    q("ALTER USER %s@'localhost' IDENTIFIED BY %s", user, bot.password if user == bot.username else data.password)
q(f"GRANT ALL PRIVILEGES ON `{bot.database}`.* TO %s@'localhost'", bot.username)
q(f"GRANT SELECT, SHOW VIEW ON `{data.database}`.* TO %s@'localhost'", data.username)          # ERP copy stays read-only for VERONICA
sync_pw = getpass.getpass("Password for the Oracle sync login 'oracle_sync' (Enter = skip): ")
if sync_pw:
    q("CREATE USER IF NOT EXISTS 'oracle_sync'@'localhost' IDENTIFIED BY %s", sync_pw)
    q("ALTER USER 'oracle_sync'@'localhost' IDENTIFIED BY %s", sync_pw)
    q(f"GRANT ALL PRIVILEGES ON `{data.database}`.* TO 'oracle_sync'@'localhost'")
q("FLUSH PRIVILEGES")
print("Databases and logins ready.")
mysql = next(iter(sorted(glob.glob(r"C:\Program Files\MySQL\MySQL Server *\bin\mysql.exe"), reverse=True)), None)
for db in (bot.database, data.database):
    f = ROOT / "db_export" / f"{db}.sql"
    if not f.exists():
        print(f"{db}: no dump at {f} - skipped"); continue
    print(f"Loading {db} ({f.stat().st_size/1e6:.1f} MB)...")
    with open(f, "rb") as fh:
        r = subprocess.run([mysql, f"-h{host}", f"-P{port}", "-uroot", "--default-character-set=utf8mb4", db],
                           stdin=fh, stderr=subprocess.PIPE, env=dict(os.environ, MYSQL_PWD=rootpw))
    print(f"  {db}: {'OK' if r.returncode == 0 else 'FAILED ' + r.stderr.decode(errors='ignore')[:200]}")
for db in (bot.database, data.database):
    cur.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=%s", (db,)); print(f"{db}: {cur.fetchone()[0]} tables")
