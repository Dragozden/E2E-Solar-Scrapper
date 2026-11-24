"""Additional fail-closed layouts. All output remains manual-review evidence."""
from __future__ import annotations
import re
from scraper.panel_pdf_stc import (_word_rows, normalize, row_type, METRICS,
    _SPATIAL_LABELS, find_stc_candidates)


def _center(w):
    return (float(w['x0']) + float(w['x1'])) / 2


def _nums(row):
    return [(_center(w), float(w['text'].replace(',', '.'))) for w in row['words']
            if re.fullmatch(r'\d{1,4}(?:[.,]\d{1,4})?', w['text'])]


def _result(fields, power, page, family):
    if set(fields) != set(METRICS):
        return []
    lines = ['ELECTRICAL CHARACTERISTICS (STC)'] + [
        _SPATIAL_LABELS[k] + ' ' + ' '.join(str(v) for v in fields[k]) for k in METRICS]
    return find_stc_candidates(lines, power, page=page, model_family=family)


def paired_conditions(words, model, power, page, family):
    """Explicit model header + alternating condition row + aligned data cells."""
    rows = _word_rows(words, tolerance=4)
    found = []
    for i, row in enumerate(rows):
        text = normalize(row['text'])
        if not re.search(r'^(testing condition|warunek testowy)\b', text) or i < 2:
            continue
        conditions = [w for w in row['words'] if w['text'].upper() in ('STC','NOCT','NMOT')]
        if not 4 <= len(conditions) <= 24 or len(conditions) % 2:
            continue
        tags = [w['text'].upper() for w in conditions]
        if tags[0::2] != ['STC']*(len(tags)//2) or len(set(tags[1::2])) != 1 or tags[1] not in ('NOCT','NMOT'):
            continue
        header = rows[i-1]['text']
        if not re.search(r'^(module type|rodzaj modulu)\b', normalize(header)):
            continue
        # The heading can itself mention both conditions; use the explicit condition row.
        if not any(re.search(r'electrical characteristics|charakterystyka elektryczna', normalize(r['text']))
                   and 'stc' in normalize(r['text']) for r in rows[max(0,i-5):i-1]):
            continue
        m = re.fullmatch(r'(LR7-\d{2}HV[A-Z])-(\d{3})M', model.upper())
        if not m or int(m[2]) != power:
            continue
        ids = re.findall(re.escape(m[1])+r'\s*-\s*(\d{3})M\b', header.upper())
        n = len(tags)//2
        if len(ids)!=n or len(set(ids))!=n or str(power) not in ids:
            continue
        xs = [_center(w) for w in conditions]
        if any(b-a<10 for a,b in zip(xs,xs[1:])):
            continue
        fields = {}
        for r in rows[i+1:i+7]:
            k = row_type(r['text']); values = _nums(r)
            if k is None or k in fields:
                break
            expected = [(a+b)/2 for a,b in zip(xs[::2],xs[1::2])] if k=='efficiency_pct' else xs
            if len(values)!=len(expected) or any(abs(x-y)>5 for (x,_),y in zip(values,expected)):
                break
            fields[k] = [v for _,v in values] if k=='efficiency_pct' else [v for _,v in values[::2]]
        if fields.get('rated_power_w') != [float(p) for p in ids]:
            continue
        found.extend(_result(fields,power,page,family))
    return found if len(found)==1 else []


def jinko_range(text, model, power):
    """Require explicit JKM start/end range with exact suffix, not just family digits."""
    m = re.fullmatch(r'JKM(\d{3})(N?-\d{2}[A-Z0-9]+-[A-Z0-9]+)', model.upper())
    if not m or int(m[1]) != power:
        return None
    matches = {(int(a),int(b)) for a,b in re.findall(
        r'\bJKM(\d{3})\s*[-~–]\s*(\d{3})'+re.escape(m[2])+r'(?:-F2C1-US)?(?![A-Z0-9-])',text.upper())}
    if len(matches)!=1:
        return None
    lo,hi=next(iter(matches))
    return (lo,hi) if lo<=power<=hi else None


def jinko_specs(page_obj, power, page, family, bounds):
    """Left-side Specifications (STC) table, separated from drawing column."""
    rows = _word_rows(page_obj.extract_words(x_tolerance=2,y_tolerance=3), tolerance=4)
    found=[]
    for row in rows:
        if not re.fullmatch(r'specifications\s*\(stc\)', normalize(row['text']).strip()):
            continue
        if row['words'][0]['x0']>page_obj.width*.2:
            continue
        # Require the known left-table/right-drawing layout; reject missing rows.
        region=page_obj.crop((0,row['top']-2,page_obj.width*.58,min(page_obj.height,row['top']+100)))
        lines=(region.extract_text(x_tolerance=2,y_tolerance=5) or '').splitlines()
        fields={}
        from scraper.panel_pdf_stc import _numbers_after_label
        for line in lines[1:]:
            k=row_type(line)
            if k is None:
                if fields: break
                continue
            if k in fields: break
            fields[k]=_numbers_after_label(line,k)
        powers=fields.get('rated_power_w',[])
        if not powers or powers[0]!=bounds[0] or powers[-1]!=bounds[1] or powers!=sorted(set(powers)):
            continue
        if any(len(v)!=len(powers) for v in fields.values()):
            continue
        found.extend(_result(fields,power,page,family))
    return found if len(found)==1 else []
