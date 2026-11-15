"""Rebuild app/static/index.html from its parts (edit the parts, then run:  python -m tools.build_ui)."""
from pathlib import Path

P = Path(__file__).resolve().parent.parent / "app" / "static"
parts = P / "_parts"
html = ((parts / "a_head.html").read_text(encoding="utf-8") + (parts / "b_body.html").read_text(encoding="utf-8")
        + (parts / "b_core.js").read_text(encoding="utf-8") + "<script>\n" + (parts / "c_holo.js").read_text(encoding="utf-8")
        + "\n" + (parts / "c_holo_os.js").read_text(encoding="utf-8")
        + "\n" + (parts / "c_atlas.js").read_text(encoding="utf-8")
        + "\n" + (parts / "c_forge.js").read_text(encoding="utf-8")
        + "\n" + (parts / "c_gesture.js").read_text(encoding="utf-8")
        + "\n" + (parts / "c_arckey.js").read_text(encoding="utf-8")
        + "\n" + (parts / "c_manip.js").read_text(encoding="utf-8")
        + "\n" + (parts / "c_worldmap.js").read_text(encoding="utf-8")
        + "\n" + (parts / "c_rail.js").read_text(encoding="utf-8") + "\n</script>\n<script>\n" + (parts / "c_voice.js").read_text(encoding="utf-8")
        + "\n</script>\n" + (parts / "d_end.js").read_text(encoding="utf-8"))
(P / "index.html").write_text(html, encoding="utf-8")
print(f"index.html rebuilt ({len(html):,} bytes)")
