"""Conservative reconstruction of split-model-header JA Solar STC OCR tables.
Output is evidence only, not an approval report. No OCR or database access.
"""
from __future__ import annotations
import math
import re
from statistics import median


class TableError(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise TableError(reason)


def center(w):
    return w['top'] + w['height'] / 2


def right(w):
    return w['left'] + w['width']


def lines(words, tolerance):
    rows = []
    for word in sorted(words, key=center):
        if not rows or abs(center(word) - median(map(center, rows[-1]))) > tolerance:
            rows.append([word])
        else:
            rows[-1].append(word)
    return [sorted(row, key=lambda w: w['left']) for row in rows]


def text(row):
    return ' '.join(w['text'] for w in row)


def compact(s):
    return re.sub(r'[^a-z0-9]', '', s.lower())


LABELS = {
    'rated_power_w': r'ratedmax(?:imum)?powerpmaxw',
    'voc_v': r'opencircuitvoltagevocv',
    'vmp_v': r'm?aximumpowervoltagevmpv',
    'isc_a': r'shortcircuitcurrentisca',
    'imp_a': r'm?aximumpowercurrentimpa',
    'efficiency_pct': r'm?oduleefficiency',
}


def reconstruct(evidence):
    require(evidence.get('status') == 'OCR_EVIDENCE_ONLY' and evidence.get('database_write') is False
            and evidence.get('candidates') == [], 'NOT_RAW_OCR_EVIDENCE')
    model = evidence.get('model_requested')
    power = evidence.get('power_w_requested')
    match = re.fullmatch(r'(JAM\d{2}D\d{2})-(\d{3})/(LB|LR|MB)', model or '')
    require(match and type(power) is int and int(match[2]) == power, 'UNSUPPORTED_MODEL_LAYOUT')
    family, suffix = match[1], match[3]
    width, height = evidence.get('image_width'), evidence.get('image_height')
    require(type(width) is int and type(height) is int and 0 < width*height <= 20_000_000
            and width > 0 and height > 0, 'INVALID_IMAGE_SIZE')
    words = evidence.get('ocr_words')
    require(isinstance(words, list) and 0 < len(words) <= 10000, 'INVALID_WORD_COUNT')
    for w in words:
        require(isinstance(w, dict) and isinstance(w.get('text'), str) and 0 < len(w['text']) <= 300,
                'INVALID_WORD')
        require(all(type(w.get(k)) is int for k in ('left','top','width','height'))
                and w['left'] >= 0 and w['top'] >= 0 and w['width'] > 0 and w['height'] > 0
                and right(w) <= width and w['top']+w['height'] <= height, 'INVALID_WORD_BOX')
        require(type(w.get('confidence')) in (float,int) and math.isfinite(w['confidence'])
                and 0 <= w['confidence'] <= 100, 'INVALID_CONFIDENCE')
    # Page-relative tolerances derived from typical glyph height, not fixed coordinates.
    h = median(w['height'] for w in words if w['confidence'] >= 60) if any(w['confidence'] >= 60 for w in words) else 0
    require(h > 0, 'NO_RELIABLE_TEXT')
    rows = lines(words, h * .65)
    heads = []
    for row in rows:
        for i in range(len(row)-3):
            group = row[i:i+4]
            if text(group).upper() == 'ELECTRICAL PARAMETERS AT STC' and min(w['confidence'] for w in group) >= 80:
                heads.append(group)
    require(len(heads) == 1, 'STC_HEADING_NOT_UNIQUE')
    head = heads[0]; hy = median(map(center, head)); left = head[0]['left']
    # Anchor the table by its exact split model header and suffix row. Other page columns are ignored.
    family_rows = [r for r in rows if hy < median(map(center,r)) < hy + 9*h
                   and sum(w['text'].upper() == family for w in r) >= 2]
    require(len(family_rows) == 1, 'MODEL_FAMILY_ROW_NOT_UNIQUE')
    headers = [w for w in family_rows[0] if w['text'].upper() == family]
    n = len(headers); require(2 <= n <= 12, 'INVALID_COLUMN_COUNT')
    edges = list(map(right, headers)); spacing = median(b-a for a,b in zip(edges,edges[1:]))
    require(spacing > 2*h and all(abs((b-a)-spacing) <= spacing*.2 for a,b in zip(edges,edges[1:])), 'IRREGULAR_COLUMNS')
    tolerance = min(spacing*.18, h*1.2)
    fy = median(map(center, headers))
    suffix_rows = [r for r in rows if fy < median(map(center,r)) < fy+3*h and any(re.fullmatch(r'-\d{3}/[A-Z]{2}',w['text']) for w in r)]
    require(len(suffix_rows) == 1, 'MODEL_VARIANT_ROW_NOT_UNIQUE')
    def aligned(row, edge):
        found = [w for w in row if abs(right(w)-edge) <= tolerance]
        require(len(found) == 1, 'MISSING_OR_AMBIGUOUS_CELL')
        return found[0]
    variants = [aligned(suffix_rows[0], e) for e in edges]
    require(all(re.fullmatch(r'-\d{3}/'+suffix,w['text']) for w in variants), 'MODEL_SUFFIX_MISMATCH')
    powers = [int(w['text'][1:4]) for w in variants]
    require(powers == sorted(set(powers)) and power in powers, 'TARGET_POWER_NOT_UNIQUE')
    col = powers.index(power)
    require(min(headers[col]['confidence'], variants[col]['confidence']) >= 80, 'LOW_MODEL_CONFIDENCE')
    sy = median(map(center, variants))
    label_limit = edges[0]-spacing*.65
    # A recognized power-tolerance row terminates the supported STC numeric table.
    stops = [r for r in rows if sy < median(map(center,r)) < sy+25*h
             and compact(text([w for w in r if left-h <= w['left'] and right(w) <= label_limit])) == 'powertolerance']
    require(len(stops) == 1, 'STC_BOUNDARY_NOT_UNIQUE')
    end = median(map(center,stops[0]))
    metrics = {}; selected = {}; row_positions = []
    for row in rows:
        y = median(map(center,row))
        if not sy < y < end: continue
        label_words = [w for w in row if left-h <= w['left'] and right(w) <= label_limit]
        label = compact(text(label_words))
        keys = [k for k,rx in LABELS.items() if re.fullmatch(rx,label)]
        if not keys: continue
        key = keys[0]; require(key not in metrics, 'DUPLICATE_METRIC_ROW')
        # Require actual numeric cells, never fill missing cells or correct digits.
        cells = [aligned(row,e) for e in edges]
        require(all(re.fullmatch(r'\d{1,3}(?:[.,]\d{1,3})?',w['text']) for w in cells), 'INVALID_NUMERIC_CELL')
        require(cells[col]['confidence'] >= 85, 'LOW_NUMERIC_CONFIDENCE')
        metrics[key] = [float(w['text'].replace(',','.')) for w in cells]
        selected[key] = dict(cells[col]); row_positions.append(key)
    require(row_positions == list(LABELS), 'MISSING_OR_REORDERED_METRICS')
    require(metrics['rated_power_w'] == powers, 'POWER_ROW_MODEL_MISMATCH')
    for i,p in enumerate(powers):
        v = {k:values[i] for k,values in metrics.items()}
        require(0 < v['vmp_v'] < v['voc_v'] and 0 < v['imp_a'] < v['isc_a'] and 0 < v['efficiency_pct'] <= 35
                and abs(v['vmp_v']*v['imp_a']-p)/p <= .02, 'ELECTRICAL_CONSISTENCY_FAILED')
    return dict(status='OCR_TABLE_REVIEW_REQUIRED', model_requested=model, power_w_requested=power,
                pdf_sha256=evidence['pdf_sha256'], page=evidence['page'], variant_column_zero_based=col,
                column_powers=powers, table_values=metrics, proposed_values={k:v[col] for k,v in metrics.items()},
                selected_tokens=selected, model_tokens=[headers[col],variants[col]], database_write=False,
                warning='Evidence only; visually verify original PDF. Not accepted by approve_panel_pdf.py.')
