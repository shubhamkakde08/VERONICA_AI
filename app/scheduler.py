"""Scheduled reports: e.g. /daily_sales every day 9 AM to the Sales Telegram group."""
from __future__ import annotations

import logging
import traceback
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from . import config, store

log = logging.getLogger("veronica.scheduler")
TZ = ZoneInfo(config.TIMEZONE)
_sched = BackgroundScheduler(timezone=TZ)


def validate_cron(cron: str) -> None:
    try:
        CronTrigger.from_crontab(cron, timezone=TZ)
    except Exception as e:
        raise ValueError(f"Invalid cron '{cron}': {e}") from e


def run_schedule(schedule_id: int) -> dict:
    """Runs one scheduled report now and sends it to its Telegram chat."""
    from . import agent, telegram  # late import
    sch = next((s for s in store.list_schedules() if s["id"] == schedule_id), None)
    if not sch:
        return {"error": "schedule not found or inactive"}
    owner = store.get_user(sch["owner_user_id"]) if sch["owner_user_id"] else None
    if not owner:
        return {"error": "schedule owner missing"}
    text = (f"/{sch['skill_name']} {sch['prompt'] or ''}\n"
            f"(Automatic scheduled run '{sch['name']}'. Do not ask questions - use the skill's "
            f"default period and filters. Output formats: {sch['formats']}.)")
    try:
        reply = agent.handle_message(owner, text, channel="schedule",
                                     chat_key=f"sched:{schedule_id}", remember=False)
        _deliver(sch, reply)
        store.mark_schedule_run(schedule_id)
        return {"ok": True, "report_ids": reply.report_ids}
    except Exception as e:
        traceback.print_exc()
        try:
            tgt = str(sch["target_chat_id"] or "")
            if tgt.startswith("email:"):
                from . import outbox
                outbox.send_email([tgt[6:]], f"Scheduled report failed: {sch['name']}", f"⚠️ Scheduled report '{sch['name']}' failed: {e}", [])
            elif config.TELEGRAM_ENABLED:
                telegram.send_text(tgt, f"⚠️ Scheduled report '{sch['name']}' failed: {e}")
        except Exception:
            pass
        return {"error": str(e)}


def _deliver(sch: dict, reply) -> None:
    """E-mail (target 'email:addr', or any schedule while Telegram is switched off) or Telegram."""
    from . import outbox, telegram
    tgt = str(sch["target_chat_id"] or "")
    if tgt.startswith("email:") or not config.TELEGRAM_ENABLED:
        owner = store.get_user(sch["owner_user_id"]) or {}
        to = tgt[6:] if tgt.startswith("email:") else owner.get("email")
        if not to:
            raise RuntimeError("Telegram is off and the schedule owner has no e-mail saved")
        paths = [f["path"] for f in (reply.files or []) if f.get("path")]
        outbox.send_email([to], f"⏰ {sch['name']} | {config.COMPANY_NAME}",
                          (reply.text or "") + "\n\nSent automatically by " + config.ASSISTANT_NAME, paths)
    else:
        telegram.send_reply(tgt, reply, header=f"⏰ {sch['name']}")


def reload() -> None:
    """Re-sync jobs with the rb_schedules table."""
    for job in _sched.get_jobs():
        job.remove()
    for s in store.list_schedules():
        try:
            _sched.add_job(run_schedule, CronTrigger.from_crontab(s["cron"], timezone=TZ),
                           args=[s["id"]], id=f"sch_{s['id']}", replace_existing=True,
                           misfire_grace_time=600, coalesce=True)
        except Exception as e:
            log.error("bad schedule %s: %s", s["id"], e)


def next_run(schedule_id: int) -> str | None:
    job = _sched.get_job(f"sch_{schedule_id}")
    if job is None:
        return None
    nrt = getattr(job, "next_run_time", None)
    if nrt is None:  # scheduler not started yet (e.g. tests)
        nrt = job.trigger.get_next_fire_time(None, __import__("datetime").datetime.now(TZ))
    return nrt.strftime("%d-%m-%Y %H:%M") if nrt else None


def start() -> None:
    reload()
    if not _sched.running:
        _sched.start()
