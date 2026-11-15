"""The bot's own storage: users & roles, report skills (the "teach" node),
report history, schedules and chat memory.

Uses SQLAlchemy Core so it runs on MySQL in production and SQLite in tests.
Tables are created automatically on first start (see sql/bot_schema.mysql.sql
if your DBA prefers to create them by hand).
"""
from __future__ import annotations

import json
import re
import secrets
from datetime import datetime
from typing import Any

from sqlalchemy.dialects import mysql as _mysql
from sqlalchemy import (
    JSON, Boolean, Column, DateTime, ForeignKey, Integer, MetaData, String, Table,
    Text, UniqueConstraint, create_engine, delete, func, insert, or_, select, update,
)

from . import config

metadata = MetaData()
# TEXT is limited to 64 KB in MySQL; stored report queries can be larger.
BigText = Text().with_variant(_mysql.MEDIUMTEXT(), "mysql").with_variant(_mysql.MEDIUMTEXT(), "mariadb")

roles = Table(
    "rb_roles", metadata,
    Column("name", String(50), primary_key=True),
    Column("description", String(255), default=""),
    # list of table names this role may query, ["*"] = every table
    Column("allowed_tables", JSON, nullable=False, default=list),
    Column("can_teach", Boolean, default=False),
    Column("can_schedule", Boolean, default=False),
    # False = may only run taught /reports, no free-form questions on raw tables
    Column("free_query", Boolean, default=True),
    Column("is_admin", Boolean, default=False),
)

users = Table(
    "rb_users", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", String(100), nullable=False),
    Column("role", String(50), ForeignKey("rb_roles.name"), nullable=False),
    Column("telegram_id", String(32), unique=True, nullable=True),
    Column("web_token", String(64), unique=True, nullable=True),
    Column("username", String(60), unique=True, nullable=True),   # web login name
    Column("password_hash", String(200), nullable=True),           # pbkdf2, never plain text
    Column("email", String(160), nullable=True),                   # for "send it to X by mail"
    Column("phone", String(20), nullable=True),                    # WhatsApp number, with country code
    Column("division", String(10), nullable=True),
    Column("themes", String(80), nullable=True),
    Column("issue_plants", Text, nullable=True),                     # Issue dashboard: only these PLANT_NAMEs (JSON list); empty = all
    Column("scrap_lines", String(255), nullable=True),               # Scrap MIS: only these plant lines (comma keys); empty = all                    # looks this user may use (comma list); empty = all                 # U1 / U2 = this user sees only that division's data
    Column("active", Boolean, default=True),
    Column("security_alerts", Boolean, nullable=True),               # get security alert mails: None = default (admins yes, others no)
    Column("created_at", DateTime, default=datetime.utcnow),
)

sessions = Table(
    "rb_sessions", metadata,
    Column("token", String(64), primary_key=True),
    Column("user_id", Integer, ForeignKey("rb_users.id"), nullable=False, index=True),
    Column("expires_at", DateTime, nullable=False),
    Column("created_at", DateTime, default=datetime.utcnow),
)

security_events = Table(            # who tried to see something outside their access (admin's audit trail)
    "rb_security_events", metadata,
    Column("id", Integer, primary_key=True),
    Column("at", DateTime, default=datetime.utcnow, index=True),
    Column("user_id", Integer, nullable=True),
    Column("user_name", String(120), default=""),
    Column("role", String(60), default=""),
    Column("channel", String(20), default=""),
    Column("kind", String(40), default=""),
    Column("detail", Text, nullable=True),
    Column("request_text", Text, nullable=True),
    Column("ip", String(64), default=""),
)

skills = Table(
    "rb_skills", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", String(60), unique=True, nullable=False),  # used as /name
    Column("title", String(200), nullable=False),
    Column("description", Text, default=""),
    Column("rules", Text, default=""),            # business rules & regulations
    Column("output_format", Text, default=""),    # columns, order, totals, layout
    Column("default_formats", String(100), default="table"),  # table,excel,pdf,chart,html
    Column("sql_template", BigText, default=""),  # reference SQL or JSON with stored queries
    Column("example_output", Text, default=""),   # a sample of the desired report
    Column("allowed_roles", JSON, default=list),  # [] = everyone
    Column("version", Integer, default=1),
    Column("created_by", String(100), default=""),
    Column("updated_at", DateTime, default=datetime.utcnow, onupdate=datetime.utcnow),
    Column("active", Boolean, default=True),
)

skill_versions = Table(
    "rb_skill_versions", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("skill_name", String(60), nullable=False, index=True),
    Column("version", Integer, nullable=False),
    Column("snapshot", JSON, nullable=False),
    Column("changed_by", String(100), default=""),
    Column("created_at", DateTime, default=datetime.utcnow),
    UniqueConstraint("skill_name", "version"),
)

reports = Table(
    "rb_reports", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", Integer, ForeignKey("rb_users.id"), nullable=True),
    Column("channel", String(20), default="web"),  # web | telegram | schedule | n8n
    Column("skill_name", String(60), default="", index=True),
    Column("title", String(200), default=""),
    Column("request_text", Text, default=""),
    Column("sql_text", BigText, default=""),
    Column("row_count", Integer, default=0),
    Column("summary", Text, default=""),
    Column("files", JSON, default=list),          # [{"format":"excel","path":"...","url":"..."}]
    Column("data_preview", JSON, default=list),   # first rows, for "compare with last time"
    Column("created_at", DateTime, default=datetime.utcnow, index=True),
)

schedules = Table(
    "rb_schedules", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", String(100), nullable=False),
    Column("skill_name", String(60), nullable=False),
    Column("cron", String(100), nullable=False),        # "0 9 * * 1-6"
    Column("prompt", Text, default=""),                 # extra instructions e.g. "for yesterday"
    Column("formats", String(100), default="excel"),
    Column("target_chat_id", String(32), nullable=False),  # Telegram chat / group id
    Column("owner_user_id", Integer, ForeignKey("rb_users.id"), nullable=True),
    Column("active", Boolean, default=True),
    Column("last_run_at", DateTime, nullable=True),
    Column("created_at", DateTime, default=datetime.utcnow),
)

messages = Table(
    "rb_messages", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("chat_key", String(80), nullable=False, index=True),  # "tg:123" / "web:5"
    Column("role", String(20), nullable=False),  # user | assistant
    Column("content", Text, nullable=False),
    Column("created_at", DateTime, default=datetime.utcnow),
)

engine = create_engine(config.BOT_DB_URL, pool_pre_ping=True, pool_recycle=1800, future=True)

SKILL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,59}$")
RESERVED_COMMANDS = {
    "start", "help", "teach", "skills", "history", "schedules", "myid", "new",
    "adduser", "lang", "cancel",
}


def _row(r) -> dict | None:
    return dict(r._mapping) if r is not None else None


def _upgrade_existing_tables() -> None:
    """Adds columns introduced after the first install (create_all never alters tables)."""
    from sqlalchemy import inspect, text
    cols = {c["name"] for c in inspect(engine).get_columns("rb_users")}
    with engine.begin() as c:
        if "username" not in cols:
            c.execute(text("ALTER TABLE rb_users ADD COLUMN username VARCHAR(60) NULL"))
            c.execute(text("CREATE UNIQUE INDEX ux_rb_users_username ON rb_users (username)"))
        if "password_hash" not in cols:
            c.execute(text("ALTER TABLE rb_users ADD COLUMN password_hash VARCHAR(200) NULL"))
        if "email" not in cols:
            c.execute(text("ALTER TABLE rb_users ADD COLUMN email VARCHAR(160) NULL"))
        if "phone" not in cols:
            c.execute(text("ALTER TABLE rb_users ADD COLUMN phone VARCHAR(20) NULL"))
        if "division" not in cols:
            c.execute(text("ALTER TABLE rb_users ADD COLUMN division VARCHAR(10) NULL"))
        if "themes" not in cols:
            c.execute(text("ALTER TABLE rb_users ADD COLUMN themes VARCHAR(80) NULL"))
        if "scrap_lines" not in cols:
            c.execute(text("ALTER TABLE rb_users ADD COLUMN scrap_lines VARCHAR(255) NULL"))
        if "issue_plants" not in cols:
            c.execute(text("ALTER TABLE rb_users ADD COLUMN issue_plants TEXT NULL"))
        if "security_alerts" not in cols:
            c.execute(text("ALTER TABLE rb_users ADD COLUMN security_alerts BOOLEAN NULL"))
    if engine.dialect.name in ("mysql", "mariadb"):
        insp = inspect(engine)
        with engine.begin() as c:
            for table, col in (("rb_skills", "sql_template"), ("rb_reports", "sql_text")):
                t = {x["name"]: str(x["type"]).upper() for x in insp.get_columns(table)}.get(col, "")
                if t in ("TEXT", "TINYTEXT"):
                    c.execute(text(f"ALTER TABLE {table} MODIFY {col} MEDIUMTEXT"))


def init_db() -> None:
    metadata.create_all(engine)
    _upgrade_existing_tables()
    with engine.begin() as c:
        if not c.execute(select(func.count()).select_from(roles)).scalar():
            c.execute(insert(roles), [
                {"name": "admin", "description": "Everything", "allowed_tables": ["*"],
                 "can_teach": True, "can_schedule": True, "free_query": True, "is_admin": True},
                {"name": "manager", "description": "All data, can teach & schedule",
                 "allowed_tables": ["*"], "can_teach": True, "can_schedule": True,
                 "free_query": True, "is_admin": False},
                {"name": "viewer", "description": "Runs taught reports only",
                 "allowed_tables": ["*"], "can_teach": False, "can_schedule": False,
                 "free_query": False, "is_admin": False},
            ])
        if not c.execute(select(func.count()).select_from(users)).scalar():
            c.execute(insert(users).values(
                name=config.BOOTSTRAP_ADMIN_NAME, role="admin",
                telegram_id=config.BOOTSTRAP_ADMIN_TELEGRAM_ID or None,
                web_token=config.BOOTSTRAP_ADMIN_WEB_TOKEN or secrets.token_urlsafe(24),
            ))


# ---------------------------------------------------------------- users / roles
def get_user_by_telegram(tg_id: str | int) -> dict | None:
    with engine.connect() as c:
        return _row(c.execute(select(users).where(
            users.c.telegram_id == str(tg_id), users.c.active.is_(True))).first())


def get_user_by_token(token: str) -> dict | None:
    if not token:
        return None
    with engine.connect() as c:
        return _row(c.execute(select(users).where(
            users.c.web_token == token, users.c.active.is_(True))).first())


def get_user(user_id: int) -> dict | None:
    with engine.connect() as c:
        return _row(c.execute(select(users).where(users.c.id == user_id)).first())


def get_role(name: str) -> dict:
    with engine.connect() as c:
        r = _row(c.execute(select(roles).where(roles.c.name == name)).first())
    return r or {"name": name, "allowed_tables": [], "can_teach": False,
                 "can_schedule": False, "free_query": False, "is_admin": False}


def add_user(name: str, role: str, telegram_id: str | None = None) -> dict:
    token = secrets.token_urlsafe(24)
    with engine.begin() as c:
        res = c.execute(insert(users).values(
            name=name, role=role, telegram_id=telegram_id or None, web_token=token))
        uid = res.inserted_primary_key[0]
    return get_user(uid)


# ---------------------------------------------------------------- web login
import hashlib
from datetime import timedelta

PBKDF2_ROUNDS = 200_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PBKDF2_ROUNDS).hex()
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${salt}${digest}"


_DUMMY_HASH = f"pbkdf2_sha256${PBKDF2_ROUNDS}${'0' * 32}${'0' * 64}"


def check_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        _, rounds, salt, digest = stored.split("$")
    except ValueError:
        return False
    test = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(rounds)).hex()
    return secrets.compare_digest(test, digest)


def set_login(user_id: int, username: str, password: str) -> None:
    username = username.strip().lower()
    if not re.match(r"^[a-z0-9._-]{3,60}$", username):
        raise ValueError("Username: 3-60 characters, letters/numbers/. _ - only")
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters")
    with engine.begin() as c:
        clash = c.execute(select(users.c.id).where(users.c.username == username,
                                                   users.c.id != user_id)).first()
        if clash:
            raise ValueError(f"Username '{username}' is already used")
        c.execute(update(users).where(users.c.id == user_id).values(
            username=username, password_hash=hash_password(password)))
        c.execute(delete(sessions).where(sessions.c.user_id == user_id))  # log out everywhere


def change_password(user_id: int, old: str, new: str) -> None:
    u = get_user(user_id)
    if not u or not check_password(old, u.get("password_hash")):
        raise ValueError("Current password is wrong")
    set_login(user_id, u["username"], new)


def rename_username(user_id: int, new: str) -> str:
    """Change only the login name (password, role, history stay). Login is case-insensitive."""
    new = (new or "").strip().lower()
    if not re.match(r"^[a-z0-9._-]{3,60}$", new):
        raise ValueError("Username must be 3-60 letters/digits (. _ - allowed)")
    with engine.begin() as c:
        clash = c.execute(select(users.c.id).where(users.c.username == new, users.c.id != user_id)).first()
        if clash:
            raise ValueError(f"Username '{new}' is already used by user #{clash[0]}")
        c.execute(update(users).where(users.c.id == user_id).values(username=new))
    return new


def authenticate(username: str, password: str) -> dict | None:
    with engine.connect() as c:
        u = _row(c.execute(select(users).where(
            users.c.username == username.strip().lower(), users.c.active.is_(True))).first())
    if not u:                                   # unknown login: spend the same hashing time as a real check
        check_password(password, _DUMMY_HASH)
        return None
    return u if check_password(password, u.get("password_hash")) else None


def create_session(user_id: int, hours: int) -> str:
    token = secrets.token_urlsafe(32)
    with engine.begin() as c:
        c.execute(delete(sessions).where(sessions.c.expires_at < datetime.utcnow()))
        c.execute(insert(sessions).values(token=token, user_id=user_id,
                                          expires_at=datetime.utcnow() + timedelta(hours=hours)))
    return token


def get_user_by_session(token: str) -> dict | None:
    if not token:
        return None
    with engine.connect() as c:
        row = c.execute(select(users).join(sessions, sessions.c.user_id == users.c.id).where(
            sessions.c.token == token, sessions.c.expires_at > datetime.utcnow(),
            users.c.active.is_(True))).first()
    return _row(row)


def end_session(token: str) -> None:
    with engine.begin() as c:
        c.execute(delete(sessions).where(sessions.c.token == token))


def end_all_sessions(user_id: int) -> None:
    with engine.begin() as c:
        c.execute(delete(sessions).where(sessions.c.user_id == user_id))


def gets_security_alerts(user: dict) -> bool:
    """Admin-controlled per person (e.g. the director). Not set yet -> admins get alerts, everyone else not."""
    v = user.get("security_alerts")
    if v is not None:
        return bool(v)
    try:
        return bool(get_role(user["role"]).get("is_admin"))
    except Exception:
        return False


def set_security_alerts(user_id: int, on: bool) -> None:
    with engine.begin() as c:
        c.execute(update(users).where(users.c.id == user_id).values(security_alerts=bool(on)))


def set_active(user_id: int, active: bool) -> None:
    with engine.begin() as c:
        c.execute(update(users).where(users.c.id == user_id).values(active=active))
        if not active:
            c.execute(delete(sessions).where(sessions.c.user_id == user_id))


def list_users() -> list[dict]:
    with engine.connect() as c:
        return [_row(r) for r in c.execute(select(users).order_by(users.c.id))]


# ---------------------------------------------------------------- security audit
def add_security_event(user: dict | None, kind: str, detail: str, channel: str = "", request_text: str = "",
                       ip: str = "") -> int:
    u = user or {}
    with engine.begin() as c:
        r = c.execute(insert(security_events).values(
            at=datetime.utcnow(), user_id=u.get("id"), user_name=(u.get("name") or u.get("username") or "?")[:120],
            role=(u.get("role") or "")[:60], channel=(channel or "")[:20], kind=kind[:40],
            detail=(detail or "")[:4000], request_text=(request_text or "")[:4000], ip=(ip or "")[:64]))
        return int(r.inserted_primary_key[0])


def list_security_events(days: int = 30, limit: int = 500) -> list[dict]:
    since = datetime.utcnow() - timedelta(days=days)
    with engine.connect() as c:
        return [_row(r) for r in c.execute(select(security_events).where(security_events.c.at >= since)
                                           .order_by(security_events.c.id.desc()).limit(limit))]


# ---------------------------------------------------------------- skills
def normalize_skill_name(name: str) -> str:
    n = re.sub(r"[^a-z0-9_]+", "_", name.strip().lstrip("/").lower()).strip("_")
    if n and n[0].isdigit():
        n = "r_" + n
    return n[:60]


def get_skill(name: str) -> dict | None:
    with engine.connect() as c:
        return _row(c.execute(select(skills).where(
            skills.c.name == normalize_skill_name(name), skills.c.active.is_(True))).first())


def skill_allowed(skill: dict, user: dict) -> bool:
    """Role must be listed on the report (or the report is open to all) AND the role must be able
    to read at least one of the report's views - so a Purchase user never even sees a production report."""
    from .access import skill_tables, table_ok
    allowed = skill.get("allowed_roles") or []
    role = get_role(user["role"])
    if role.get("is_admin"):
        return True
    if allowed and user["role"] not in allowed:
        return False
    views = skill_tables(skill)
    return not views or any(table_ok(v, role.get("allowed_tables") or []) for v in views)


def list_roles() -> list[dict]:
    with engine.connect() as c:
        return [_row(r) for r in c.execute(select(roles).order_by(roles.c.name))]


def save_role(name: str, allowed_tables: list[str], description: str = "", can_teach: bool = False,
              can_schedule: bool = False, free_query: bool = True, is_admin: bool = False) -> dict:
    name = name.strip().lower()
    if not re.match(r"^[a-z][a-z0-9_]{1,40}$", name):
        raise ValueError("Role name: letters/numbers/underscore, e.g. production")
    vals = dict(description=description, allowed_tables=allowed_tables, can_teach=can_teach,
                can_schedule=can_schedule, free_query=free_query, is_admin=is_admin)
    with engine.begin() as c:
        if c.execute(select(roles.c.name).where(roles.c.name == name)).first():
            c.execute(update(roles).where(roles.c.name == name).values(**vals))
        else:
            c.execute(insert(roles).values(name=name, **vals))
    return get_role(name)


def delete_role(name: str) -> bool:
    with engine.begin() as c:
        return c.execute(delete(roles).where(roles.c.name == name)).rowcount > 0


def set_user_role(user_id: int, role: str) -> None:
    if not any(r["name"] == role for r in list_roles()):
        raise ValueError(f"role '{role}' does not exist (see: roles)")
    with engine.begin() as c:
        c.execute(update(users).where(users.c.id == user_id).values(role=role))


def delete_user(user_id: int) -> dict:
    """Remove a user for good: sessions + chat history deleted, their schedules removed,
    saved reports kept (marked as no owner) for audit."""
    u = get_user(user_id)
    if not u:
        raise ValueError(f"no user #{user_id}")
    admins = [x for x in list_users() if get_role(x["role"]).get("is_admin") and x.get("active", True)]
    if get_role(u["role"]).get("is_admin") and len(admins) <= 1:
        raise ValueError("this is the last active admin - make someone else admin first")
    with engine.begin() as c:
        c.execute(delete(sessions).where(sessions.c.user_id == user_id))
        c.execute(delete(schedules).where(schedules.c.owner_user_id == user_id))
        c.execute(update(reports).where(reports.c.user_id == user_id).values(user_id=None))
        keys = [f"web:{user_id}"] + ([f"tg:{u['telegram_id']}"] if u.get("telegram_id") else [])
        c.execute(delete(messages).where(messages.c.chat_key.in_(keys)))
        c.execute(delete(users).where(users.c.id == user_id))
    return u


def rename_user(user_id: int, name: str) -> None:
    name = " ".join(name.split())
    if not name:
        raise ValueError("name is empty")
    with engine.begin() as c:
        c.execute(update(users).where(users.c.id == user_id).values(name=name[:100]))


def set_user_contact(user_id: int, email: str | None = None, phone: str | None = None) -> None:
    vals = {}
    if email is not None:
        vals["email"] = email.strip() or None
    if phone is not None:
        vals["phone"] = re.sub(r"[^0-9]", "", phone) or None
    if vals:
        with engine.begin() as c:
            c.execute(update(users).where(users.c.id == user_id).values(**vals))


THEMES = ["aurora", "arc", "holo", "forge", "titan", "atlas"]          # Nova retired (old ticks read as Holo)
POWER_ONLY_THEMES = {"atlas"}        # only admin / manager roles, even if ticked for someone else


def is_power(user: dict) -> bool:
    """Admin / manager roles (config.POWER_ROLES): hand gestures + all themes."""
    from . import config
    return (user.get("role") or "").lower() in config.POWER_ROLES or bool(get_role(user.get("role") or "").get("is_admin"))


def user_themes(user: dict) -> list[str]:
    """Looks this user may switch to. Ticked by the admin per user; not set = all for admin/manager roles,
    DEFAULT_THEMES (Aurora) for everyone else."""
    from . import config
    power = is_power(user)
    got = [("holo" if t == "nova" else t) for t in (user.get("themes") or "").replace(" ", "").lower().split(",")]
    got = list(dict.fromkeys(t for t in got if t in THEMES and (power or t not in POWER_ONLY_THEMES)))
    if got:
        return got
    return list(THEMES) if power else ([t for t in THEMES if t in config.DEFAULT_THEMES and t not in POWER_ONLY_THEMES] or ["aurora"])


def set_user_themes(user_id: int, themes: list[str] | str | None) -> list[str]:
    if isinstance(themes, str):
        themes = themes.replace(" ", ",").split(",")
    keep = [t for t in THEMES if t in {x.strip().lower() for x in (themes or [])}]
    with engine.begin() as c:
        c.execute(update(users).where(users.c.id == user_id).values(themes=",".join(keep) if keep else None))
    return keep or list(THEMES)


SCRAP_LINES = {   # Scrap MIS report lines (plant rows) a user can be limited to
    "W_WELDED": "Welded", "W_TM10": "TM10", "W_COND": "Cond", "W_SLIT": "Slitting", "L_LSAW": "L-Saw (PLB1)",
    "S_BA": "BA", "S_PIPE1_EXP1": "SMLS Pipe (EXP1)", "S_PIPE1_PEEL": "SMLS Pipe (PEEL)", "S_PIPE1_PIL": "SMLS Pipe (ALL PILGER)",
    "S_PIPE2_PEEL3": "SMLS Pipe-2 (PEEL3)", "S_PIPE2_PIL": "SMLS Pipe-2 (ALL PILGER)", "S_TUBE": "SMLS Tube",
    "S_PIERC": "Piercing 1", "S_PIER2": "Piercing 2", "S_OTH": "M2M"}


def user_scrap_lines(user: dict) -> list[str]:
    """Scrap MIS lines this user may see ([] = no limit)."""
    return [k for k in (user.get("scrap_lines") or "").replace(" ", "").upper().split(",") if k in SCRAP_LINES]


def set_user_scrap_lines(user_id: int, lines: list[str] | str | None) -> list[str]:
    if isinstance(lines, str):
        lines = lines.replace(" ", ",").split(",")
    keep = [k for k in SCRAP_LINES if k in {x.strip().upper() for x in (lines or [])}]
    with engine.begin() as c:
        c.execute(update(users).where(users.c.id == user_id).values(
            scrap_lines=",".join(keep) if keep and len(keep) < len(SCRAP_LINES) else None))
    return keep


def user_issue_plants(user: dict) -> list[str]:
    """Issue dashboard: PLANT_NAMEs this user may see ([] = no limit)."""
    try:
        v = json.loads(user.get("issue_plants") or "[]")
    except (TypeError, ValueError):
        return []
    return [str(x).strip() for x in v if str(x).strip()] if isinstance(v, list) else []


def set_user_issue_plants(user_id: int, plants: list[str] | None) -> list[str]:
    keep = sorted({str(p).strip() for p in (plants or []) if str(p).strip()})
    with engine.begin() as c:
        c.execute(update(users).where(users.c.id == user_id).values(issue_plants=json.dumps(keep) if keep else None))
    return keep


def set_user_division(user_id: int, division: str | None) -> None:
    d = (division or "").strip().upper()
    d = d if d in ("U1", "U2") else None
    with engine.begin() as c:
        c.execute(update(users).where(users.c.id == user_id).values(division=d))


def get_user_by_phone(phone: str) -> dict | None:
    """WhatsApp sender (e.g. 919876543210) -> user, matching the last 10 digits of the saved mobile."""
    d = re.sub(r"[^0-9]", "", phone or "")[-10:]
    if len(d) < 10:
        return None
    for u in list_users():
        if u.get("active", True) and re.sub(r"[^0-9]", "", u.get("phone") or "")[-10:] == d:
            return u
    return None


def find_users(name: str) -> list[dict]:
    """Active users whose name / username contains every word of `name` (case-insensitive)."""
    words = [w for w in re.split(r"\s+", (name or "").lower()) if w and w not in ("mr", "mr.", "ms", "sir", "ji", "bhai")]
    out = []
    for u in list_users():
        hay = f"{u['name']} {u.get('username') or ''}".lower()
        if u.get("active", True) and words and all(w in hay for w in words):
            out.append(u)
    return out


def set_user_telegram(user_id: int, telegram_id: str) -> None:
    with engine.begin() as c:
        c.execute(update(users).where(users.c.telegram_id == telegram_id, users.c.id != user_id).values(telegram_id=None))
        c.execute(update(users).where(users.c.id == user_id).values(telegram_id=telegram_id))


def list_skills(user: dict | None = None) -> list[dict]:
    with engine.connect() as c:
        rows = [_row(r) for r in c.execute(
            select(skills).where(skills.c.active.is_(True)).order_by(skills.c.name))]
    if user:
        rows = [s for s in rows if skill_allowed(s, user)]
    return rows


def save_skill(data: dict[str, Any], changed_by: str) -> dict:
    """Create or update a skill. Every save also writes a version snapshot."""
    name = normalize_skill_name(data["name"])
    if not SKILL_NAME_RE.match(name):
        raise ValueError("Skill name must be letters/numbers/underscore, e.g. daily_sales")
    if name in RESERVED_COMMANDS:
        raise ValueError(f"/{name} is a built-in command, choose another name")
    fields = {k: data[k] for k in (
        "title", "description", "rules", "output_format", "default_formats",
        "sql_template", "example_output", "allowed_roles") if k in data and data[k] is not None}
    if isinstance(fields.get("default_formats"), list):
        fields["default_formats"] = ",".join(fields["default_formats"])
    with engine.begin() as c:
        existing = _row(c.execute(select(skills).where(skills.c.name == name)).first())
        if existing:
            version = (existing["version"] or 1) + 1
            c.execute(update(skills).where(skills.c.name == name).values(
                **fields, version=version, active=True, updated_at=datetime.utcnow()))
        else:
            version = 1
            fields.setdefault("title", name.replace("_", " ").title())
            c.execute(insert(skills).values(name=name, created_by=changed_by,
                                            version=1, **fields))
        snap = _row(c.execute(select(skills).where(skills.c.name == name)).first())
        snapshot = {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in snap.items()}
        c.execute(insert(skill_versions).values(
            skill_name=name, version=version, snapshot=snapshot, changed_by=changed_by))
    return get_skill(name)


def delete_skill(name: str) -> bool:
    with engine.begin() as c:
        return c.execute(update(skills).where(
            skills.c.name == normalize_skill_name(name)).values(active=False)).rowcount > 0


# ---------------------------------------------------------------- report history
def save_report(**kw) -> int:
    kw["data_preview"] = json.loads(json.dumps(kw.get("data_preview") or [], default=str))
    with engine.begin() as c:
        return c.execute(insert(reports).values(**kw)).inserted_primary_key[0]


def search_reports(user: dict, query: str = "", skill_name: str = "", limit: int = 10,
                   include_preview: bool = False) -> list[dict]:
    stmt = select(reports).order_by(reports.c.created_at.desc()).limit(limit)
    if not get_role(user["role"]).get("is_admin"):
        stmt = stmt.where(reports.c.user_id == user["id"])
    if skill_name:
        stmt = stmt.where(reports.c.skill_name == normalize_skill_name(skill_name))
    if query:
        like = f"%{query}%"
        stmt = stmt.where(or_(reports.c.title.like(like), reports.c.request_text.like(like),
                              reports.c.summary.like(like)))
    with engine.connect() as c:
        rows = [_row(r) for r in c.execute(stmt)]
    if not include_preview:
        for r in rows:
            r.pop("data_preview", None)
    return rows


def get_report(report_id: int) -> dict | None:
    with engine.connect() as c:
        return _row(c.execute(select(reports).where(reports.c.id == report_id)).first())


# ---------------------------------------------------------------- schedules
def add_schedule(**kw) -> dict:
    with engine.begin() as c:
        sid = c.execute(insert(schedules).values(**kw)).inserted_primary_key[0]
        return _row(c.execute(select(schedules).where(schedules.c.id == sid)).first())


def list_schedules(user: dict | None = None, only_active: bool = True) -> list[dict]:
    stmt = select(schedules).order_by(schedules.c.id)
    if only_active:
        stmt = stmt.where(schedules.c.active.is_(True))
    if user and not get_role(user["role"]).get("is_admin"):
        stmt = stmt.where(schedules.c.owner_user_id == user["id"])
    with engine.connect() as c:
        return [_row(r) for r in c.execute(stmt)]


def set_schedule_active(schedule_id: int, active: bool) -> None:
    with engine.begin() as c:
        c.execute(update(schedules).where(schedules.c.id == schedule_id).values(active=active))


def mark_schedule_run(schedule_id: int) -> None:
    with engine.begin() as c:
        c.execute(update(schedules).where(schedules.c.id == schedule_id)
                  .values(last_run_at=datetime.utcnow()))


# ---------------------------------------------------------------- chat memory
def add_message(chat_key: str, role: str, content: str) -> None:
    with engine.begin() as c:
        c.execute(insert(messages).values(chat_key=chat_key, role=role, content=content[:20000]))


def recent_messages(chat_key: str, turns: int) -> list[dict]:
    with engine.connect() as c:
        rows = c.execute(select(messages.c.role, messages.c.content)
                         .where(messages.c.chat_key == chat_key)
                         .order_by(messages.c.id.desc()).limit(turns * 2)).all()
    out = [{"role": r.role, "content": r.content} for r in reversed(rows)]
    while out and out[0]["role"] != "user":  # Claude requires starting with user
        out.pop(0)
    return out


def clear_chat(chat_key: str) -> None:
    with engine.begin() as c:
        c.execute(delete(messages).where(messages.c.chat_key == chat_key))
