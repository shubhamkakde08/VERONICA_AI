"""Remove every Telegram-related chat and record from VERONICA's own database (not the ERP).

    python -m tools.purge_telegram           -> shows what would be removed (nothing changes)
    python -m tools.purge_telegram --apply   -> removes it for good

Removes: chat messages from Telegram chats or that mention Telegram (questions AND VERONICA's replies),
reports asked on Telegram or mentioning it, schedules that delivered to Telegram, security-log entries
about Telegram, and the Telegram id stored on each user. Prints counts only."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sqlalchemy import delete, func, or_, select, update  # noqa: E402

from app import store  # noqa: E402

T = "%telegram%"


def low(col):
    return func.lower(func.coalesce(col, ""))


def plan():
    m, r, s, e, u = store.messages, store.reports, store.schedules, store.security_events, store.users
    return [
        ("chat messages (questions and replies)", m, or_(m.c.chat_key.like("tg:%"), low(m.c.content).like(T))),
        ("saved reports", r, or_(r.c.channel == "telegram", low(r.c.request_text).like(T), low(r.c.summary).like(T),
                                 low(r.c.title).like(T))),
        ("schedules sending to Telegram", s, ~s.c.target_chat_id.like("email:%")),
        ("security-log entries", e, or_(e.c.channel == "telegram", low(e.c.detail).like(T), low(e.c.request_text).like(T))),
    ], (u, u.c.telegram_id.isnot(None))


def main(apply: bool) -> None:
    rows, (u, ucond) = plan()
    with store.engine.begin() as c:
        for label, tbl, cond in rows:
            n = c.execute(select(func.count()).select_from(tbl).where(cond)).scalar()
            print(f"{label:42s} {n:6d}")
            if apply and n:
                c.execute(delete(tbl).where(cond))
        n = c.execute(select(func.count()).select_from(u).where(ucond)).scalar()
        print(f"{'users with a Telegram id':42s} {n:6d}")
        if apply and n:
            c.execute(update(u).where(ucond).values(telegram_id=None))
    print("REMOVED." if apply else "Nothing changed yet - run with --apply to remove these for good.")


if __name__ == "__main__":
    main("--apply" in sys.argv)
