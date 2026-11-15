"""Table-access matching shared by the SQL guard and the report list.
allowed_tables entries: exact name, glob pattern (VIEW_SCRAP_*), '*' = all, '!NAME' = never."""
from __future__ import annotations

import fnmatch
import re


def denied(allowed: list[str]) -> list[str]:
    return [a[1:].lower() for a in allowed or [] if a.startswith("!")]


def table_ok(name: str, allowed: list[str]) -> bool:
    n = (name or "").lower()
    if any(fnmatch.fnmatchcase(n, d) for d in denied(allowed)):
        return False
    pos = [a.lower() for a in allowed or [] if not a.startswith("!")]
    return "*" in pos or any(fnmatch.fnmatchcase(n, p) for p in pos)


_VIEW = re.compile(r"\bVIEW_[A-Z0-9_]+\b", re.I)


def skill_tables(skill: dict) -> set[str]:
    import json
    txt = json.dumps({k: skill.get(k) for k in ("sql_template", "rules", "description")}, default=str)
    return {m.upper() for m in _VIEW.findall(txt)}
