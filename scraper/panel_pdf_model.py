"""Conservative catalog model normalization for PDF preview planning.

Never infers missing model characters from PDF filenames or nominal power alone.
Only recognizes bounded catalog title tokens and compatible stored model text.
"""
from __future__ import annotations
import re
from scraper.panel_pdf_stc import family_token


def compact(value: str) -> str:
    return re.sub(r'[^a-z0-9]', '', value.casefold())


def legacy_match(model, title, power):
    return (isinstance(model, str) and bool(model.strip()) and len(model) <= 100
            and bool(re.search(rf'(?<!\d){power}(?!\d)', model))
            and bool(family_token(model)) and compact(model) in compact(title))


def resolve_model(model, title: str, power: int, *, explicit=False):
    """Return (model, resolution), or (None, reason). No PDF identity claim."""
    if legacy_match(model, title, power):
        return model, 'EXACT_CATALOG_TOKEN'
    if explicit:
        return None, 'MANUAL_MAP_NOT_EXACT'
    missing = model is None or (isinstance(model, str) and not model.strip())
    if not missing and (not isinstance(model, str) or len(model) > 300):
        return None, 'INVALID_MODEL_TEXT'
    # Full variant codes, not family-only descriptions. Keep all suffix letters.
    patterns = (
        ('TW', r'TWMN[HD]-\d{2}(?:HD|HE)(?P<watts>\d{3})W?'),
        ('JA', r'JAM\d{2}D\d{2}-(?P<watts>\d{3})[ /]+(?:LB|LR|MB|MR)'),
        ('RISEN', r'RSM\s*\d{2,3}-\d{2}-(?P<watts>\d{3})\s*BNDG'),
        ('HYUNDAI', r'HiT-H(?P<watts>\d{3})LE'),
    )
    matches = []
    for vendor, pattern in patterns:
        for match in re.finditer(r'(?<![A-Za-z0-9-])(?:'+pattern+r')(?![A-Za-z0-9/-])', title, re.I):
            text = match.group()
            if vendor == 'JA':
                token = re.sub(r'[ /]+', '/', text.upper())
            elif vendor == 'RISEN':
                token = re.sub(r'\s+', '', text.upper())
            else:
                token = text.upper()
            matches.append((vendor, token, int(match.group('watts'))))
    if len(matches) != 1:
        return None, 'NO_UNIQUE_SUPPORTED_TITLE_VARIANT'
    vendor, token, variant_power = matches[0]
    if variant_power != power or not legacy_match(token, title, power):
        return None, 'TITLE_VARIANT_POWER_MISMATCH'
    if missing:
        if vendor not in ('RISEN', 'HYUNDAI'):
            return None, 'MISSING_STORED_MODEL'
        return token, 'EXACT_VARIANT_FROM_TITLE'
    # Remove only a clearly delimited descriptive tail, or JA's BF frame label.
    # Never strip suffix characters from the actual manufacturer code.
    if vendor == 'TW':
        cleaned = re.split(r'\s+[—–]\s+', model.strip(), maxsplit=1)[0]
    elif vendor == 'JA':
        cleaned = re.sub(r'\s+(?:BF|FB|SF)\s*$', '', model.strip(), flags=re.I)
    else:
        cleaned = model.strip()
    if compact(cleaned) != compact(token):
        return None, 'STORED_MODEL_TITLE_DISAGREE'
    return token, 'NORMALIZED_CATALOG_TOKEN'
