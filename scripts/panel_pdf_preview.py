"""Manual-only preview of local photovoltaic manufacturer datasheets.

No downloads, no database access, no automatic writes, no OCR.
Execute: uv run --with 'pdfplumber==0.11.9' python scripts/panel_pdf_preview.py ...
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scraper.panel_pdf_stc import (find_stc_candidates, family_token, HEADING_STC,
                                    OTHER_SECTIONS, normalize, spatial_stc_candidate)


def extract_stc_lines(pdf_path: Path, *, model: str, power: int) -> tuple[list, list]:
    """Find a unique STC column: textual-first, geometry fallback, fail-closed.

    No OCR and no database writes. A PDF may have graphical heading fragments,
    left/right page columns, STC/NMOT tables and separate textbox values.
    Include actionable diagnostics instead of returning unexplained [].
    """
    import pdfplumber  # optional dependency; excluded from default scraper env

    from scraper.panel_pdf_layouts import paired_conditions, jinko_range, jinko_specs, item_unit_stc
    found = []
    diagnostic = []
    family = family_token(model)
    if not family:
        raise ValueError("Model lacks an identifiable family token; manual review required")
    with pdfplumber.open(pdf_path) as pdf:
        if len(pdf.pages) > 20:
            raise ValueError("PDF has more than 20 pages; manual inspection required")
        full_text = " ".join((pg.extract_text() or "") for pg in pdf.pages)
        clean = lambda value: re.sub(r"[^A-Z0-9]", "", value.upper())
        range_bounds = jinko_range(full_text, model, power)
        if re.search(r"installation manual", full_text[:500], re.I):
            return [], [{"warning": "INSTALLATION_MANUAL_NOT_DATASHEET"}]
        if clean(family) not in clean(full_text) and range_bounds is None:
            return [], [{"warning": "EXPECTED_MODEL_FAMILY_NOT_PRESENT_IN_PDF",
                         "family": family, "extracted_characters": len(full_text),
                         "text_layer_hint": ("LIMITED_TEXT_LAYER_MANUAL_REVIEW"
                                             if len(full_text.strip()) < 250 else "CHECK_MODEL_FAMILY")}]
        range_only = clean(family) not in clean(full_text) and range_bounds is not None
        for page_number, page in enumerate(pdf.pages, start=1):
            if range_only:
                page_candidates = jinko_specs(page, power, page_number, family, range_bounds)
                found.extend(page_candidates)
                diagnostic.append({"page": page_number, "candidates_on_page": len(page_candidates),
                                   "inspections": [{"method": "range_model_stc", "range_w": list(range_bounds)}]})
                continue
            lines = page.extract_text_lines(layout=False) or []
            heads = [line for line in lines if HEADING_STC.search(normalize(line.get("text", "")))]
            page_candidates = []
            page_notes = []
            for head in heads:
                x0 = max(0, head['x0'] - 8)
                width = page.width / 2 if page.width > 420 else page.width
                x1 = min(page.width, x0 + width + 20)
                below = [l for l in lines if l['top'] > head['bottom']
                         and l['x0'] >= x0 - 15 and l['x0'] < x1]
                stops = [l['top'] for l in below
                         if OTHER_SECTIONS.search(normalize(l.get('text', '')))]
                bottom = min(stops) if stops else min(page.height, head['bottom'] + 300)
                if bottom - head['bottom'] < 28:
                    continue
                section = page.crop((x0, head['bottom'], x1, min(page.height, bottom)))
                text = section.extract_text(x_tolerance=2, y_tolerance=3) or ''
                captured_lines = text.splitlines()
                if captured_lines and normalize(captured_lines[0]).strip() == normalize(head['text']).strip():
                    captured_lines = captured_lines[1:]
                selected_lines = [head['text']] + captured_lines
                page_notes.append({"method": "text", "heading": head['text'],
                                   "first_lines": selected_lines[1:9]})
                page_candidates.extend(find_stc_candidates(selected_lines, power,
                                       page=page_number, model_family=family))
            if not page_candidates:
                # Spatial fallback can recover split headings and rows placed
                # as individual PDF text objects. Require exact column alignment
                # and 5 physically plausible STC parameters.
                words = page.extract_words(x_tolerance=2, y_tolerance=3) or []
                spatial_found, reasons = spatial_stc_candidate(words, power,
                                             page=page_number, page_width=page.width,
                                             model_family=family)
                page_candidates.extend(spatial_found)
                page_notes.append({"method": "spatial", "word_count": len(words),
                                   "reasons": reasons})
            if not page_candidates:
                paired = paired_conditions(page.extract_words(x_tolerance=2,y_tolerance=3) or [],
                                           model, power, page_number, family)
                page_candidates.extend(paired)
                if paired:
                    page_notes.append({"method": "paired_conditions", "reason": "EXPLICIT_STC_NOCT_COLUMNS_VALIDATED"})
                elif range_bounds is not None:
                    ranged = jinko_specs(page, power, page_number, family, range_bounds)
                    page_candidates.extend(ranged)
                    if ranged:
                        page_notes.append({"method": "range_model_stc", "range_w": list(range_bounds)})
            if not page_candidates:
                wide = item_unit_stc(page.extract_words(x_tolerance=2,y_tolerance=3) or [],
                                     model, power, page_number, family, full_text)
                page_candidates.extend(wide)
                if wide:
                    page_notes.append({"method": "item_unit_stc", "reason": "FULL_WIDTH_STC_HEADER_ALIGNED"})
            if not page_candidates:
                sample = [str(line.get("text", ""))[:160] for line in lines
                          if re.search(r"stc|elektryczn|charakterystyk", normalize(line.get("text", "")))]
                page_notes.append({"text_characters": len(page.extract_text() or ""),
                                   "stc_text_examples": sample[:5],
                                   "warning": ("NO_READABLE_STC_HEADER_OR_ALIGNED_COLUMNS"
                                               if not page_candidates else "")})
            found.extend(page_candidates)
            diagnostic.append({"page": page_number, "text_headings": len(heads),
                               "candidates_on_page": len(page_candidates),
                               "inspections": page_notes})
    # Never silently select one of multiple STC interpretations.
    if len(found) != 1:
        if len(found) > 1:
            diagnostic.append({"warning": "MULTIPLE_STC_CANDIDATES_REQUIRES_MANUAL_REVIEW"})
        return [], diagnostic
    return found, diagnostic


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Offline PDF STC preview; NEVER writes to database")
    parser.add_argument('--pdf', type=Path, required=True, help='PDF downloaded manually from retailer')
    parser.add_argument('--model', required=True, help='Expected model, e.g. TWMNH-54HD505')
    parser.add_argument('--power', required=True, type=int, help='Exact variant power, e.g. 505')
    parser.add_argument('--json-output', type=Path, help='Optional local review JSON, never DB')
    args = parser.parse_args(argv)
    if args.pdf.suffix.lower() != '.pdf' or not args.pdf.is_file():
        parser.error('Provide an existing local .pdf file')
    if not 100 <= args.power <= 900:
        parser.error('--power must be in 100..900 W')
    if not re.search(rf"(?<!\d){args.power}(?!\d)", args.model):
        parser.error('--model must explicitly contain the requested --power variant')
    if args.json_output and args.json_output.resolve() == args.pdf.resolve():
        parser.error('Refusing to overwrite input PDF')
    if args.json_output and args.json_output.exists():
        parser.error('Review JSON already exists; choose another filename to preserve evidence')
    if args.pdf.stat().st_size > 20 * 1024 * 1024:
        parser.error('PDF exceeds 20 MB safety limit')
    raw = args.pdf.read_bytes()
    if not raw.startswith(b'%PDF-'):
        parser.error('Input is not a PDF file')
    digest = hashlib.sha256(raw).hexdigest()
    try:
        found, debug = extract_stc_lines(args.pdf, model=args.model, power=args.power)
    except ImportError:
        print("Missing optional pdfplumber. Run: uv run --with 'pdfplumber==0.11.9' python scripts/panel_pdf_preview.py ...", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"PDF READ FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    data = {"status": "REVIEW_REQUIRED" if len(found) == 1 else "NO_UNAMBIGUOUS_STC_TABLE",
            "model_requested": args.model, "power_w_requested": args.power,
            "pdf_sha256": digest,
            "candidates": [candidate.as_dict() for candidate in found],
            "diagnostics": debug, "database_write": False}
    print(json.dumps(data, indent=2, ensure_ascii=False))
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
        print(f"SAVED REVIEW FILE: {args.json_output}")
    if len(found) != 1:
        print('NO EXACT MATCH: inspect PDF visually; do not infer values from adjacent models or NMOT', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
