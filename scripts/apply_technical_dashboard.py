"""Idempotent, anchor-guarded Stage 11.3 integration into existing Streamlit app.

Instead of overwriting the ~22 KB app.py and erasing local UI changes, this
utility edits only four narrow integration points. It refuses an unfamiliar
app layout rather than performing a partial rewrite.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "dashboard" / "app.py"

IMPORT_LINE = "from dashboard.technical_ui import clear_technical_cache, render_technical_tab\n"
IMPORT_MARKER = "from dashboard.db import load_gold_data\n"
REFRESH_MARKER = "        get_run_quality.clear()\n"
TABS_OLD = '''overview_tab, ranking_tab, drops_tab, compare_tab, history_tab, market_tab, quality_tab = st.tabs([
    "Przegląd", "Ranking paneli", "Przeceny", "Porównanie", "Historia produktu",
    "Trendy rynku", "Jakość danych",
])'''
TABS_NEW = '''overview_tab, ranking_tab, drops_tab, compare_tab, history_tab, market_tab, quality_tab, technical_tab = st.tabs([
    "Przegląd", "Ranking paneli", "Przeceny", "Porównanie", "Historia produktu",
    "Trendy rynku", "Jakość danych", "Parametry techniczne",
])'''
TAB_BLOCK = '''# STAGE11.3-TECHNICAL-TAB
with technical_tab:
    render_technical_tab()

'''
FOOTER = '\nst.divider()\nst.caption(\n    "Źródło: publiczne oferty Soltech.'


def exactly_one(text: str, needle: str) -> None:
    if text.count(needle) != 1:
        raise RuntimeError(f"Unexpected Streamlit app structure for anchor {needle[:55]!r}; no changes made")


def patch_app(source: str) -> str:
    """Produce app update or reject. Pure; never accesses files or database."""
    if TAB_BLOCK in source:
        if (source.count(IMPORT_LINE) == 1
                and source.count("        clear_technical_cache()\n") == 1
                and source.count(TABS_NEW) == 1
                and source.count(TAB_BLOCK) == 1):
            return source
        raise RuntimeError("Partial Stage 11.3 integration detected; no changes made")
    if IMPORT_LINE in source or TABS_NEW in source or 'with technical_tab:' in source:
        raise RuntimeError("Partial Stage 11.3 integration detected; no changes made")
    for needle in (IMPORT_MARKER, REFRESH_MARKER, TABS_OLD, FOOTER):
        exactly_one(source, needle)

    updated = source.replace(IMPORT_MARKER, IMPORT_MARKER + IMPORT_LINE)
    updated = updated.replace(REFRESH_MARKER, REFRESH_MARKER + "        clear_technical_cache()\n")
    updated = updated.replace(TABS_OLD, TABS_NEW)
    updated = updated.replace(FOOTER, "\n" + TAB_BLOCK + FOOTER, 1)
    compile(updated, "dashboard/app.py", "exec")
    return updated


def main() -> int:
    parser = argparse.ArgumentParser(description="Integrate Stage 11.3 without overwriting existing app.py")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--apply", action="store_true", help="Apply an atomic edit to dashboard/app.py")
    group.add_argument("--check", action="store_true", help="Verify integration, without editing")
    args = parser.parse_args()
    if not APP.is_file():
        parser.error(f"Missing file: {APP}")
    original = APP.read_text(encoding="utf-8-sig")
    if args.check:
        if TAB_BLOCK in original:
            if patch_app(original) == original:
                print("TECHNICAL DASHBOARD INTEGRATION PASS")
                return 0
        print("TECHNICAL DASHBOARD INTEGRATION NOT APPLIED")
        return 1
    updated = patch_app(original)
    if updated == original:
        print("SKIP: Technical dashboard already integrated")
        return 0
    temporary = APP.with_name(APP.name + f".partial-{uuid4().hex}")
    try:
        temporary.write_text(updated, encoding="utf-8", newline="\n")
        os.replace(temporary, APP)
    finally:
        temporary.unlink(missing_ok=True)
    print("APPLIED: dashboard/app.py (3 integration points + technical tab)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
