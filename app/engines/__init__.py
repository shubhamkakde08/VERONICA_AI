"""Report engines: one module per dashboard.

An engine module defines ENGINE = "<name>", class EngineError(Exception) and
run(skill, from_date, to_date, allowed_tables, **opts) -> dict with keys
results, sections, kpis, files, label, prev_label, row_counts, checks.
Any module dropped in this folder is picked up automatically by load()."""
import importlib
import logging
import pkgutil

log = logging.getLogger(__name__)
_cache: dict | None = None


def load() -> dict:
    global _cache
    if _cache is None:
        found = {}
        for m in pkgutil.iter_modules(__path__):
            if m.name.startswith("_"):
                continue
            try:
                mod = importlib.import_module(f"{__name__}.{m.name}")
            except Exception:
                log.exception("engine %s failed to import", m.name)
                continue
            if getattr(mod, "ENGINE", None):
                found[mod.ENGINE] = mod
        _cache = found
    return _cache
