"""CLI security/behavior tests; no PDF renderer, internet or DB required."""
from __future__ import annotations

from pathlib import Path
import json

import pytest

from scripts import panel_pdf_preview as cli
from scraper.panel_pdf_stc import StcCandidate


def fake_pdf(tmp_path):
    path = tmp_path / 'spec.pdf'
    path.write_bytes(b'%PDF-1.7\nsynthetic test bytes')
    return path


def test_cli_writes_review_json_but_no_database(monkeypatch, tmp_path, capsys):
    pdf = fake_pdf(tmp_path)
    out = tmp_path / 'review' / '505.json'
    candidate = StcCandidate(page=2, power_w=505, variant_column=2,
                             model_family='TWMNH-54HD', values={'rated_power_w':505., 'voc_v':40.24},
                             warning='manual verification required')
    monkeypatch.setattr(cli, 'extract_stc_lines', lambda *a, **kw: ([candidate], []))
    rc = cli.main(['--pdf', str(pdf), '--model', 'TWMNH-54HD505', '--power', '505',
                   '--json-output', str(out)])
    assert rc == 0
    data = json.loads(out.read_text(encoding='utf-8'))
    assert data['status'] == 'REVIEW_REQUIRED'
    assert data['database_write'] is False
    assert data['pdf_sha256']
    assert data['candidates'][0]['page'] == 2
    assert not (tmp_path / 'bronze').exists()
    assert 'REVIEW_REQUIRED' in capsys.readouterr().out


def test_no_candidate_returns_nonzero(monkeypatch, tmp_path):
    pdf = fake_pdf(tmp_path)
    monkeypatch.setattr(cli, 'extract_stc_lines', lambda *a, **kw: ([], []))
    assert cli.main(['--pdf', str(pdf), '--model', 'TWMNH-54HD505', '--power', '505']) == 1


def test_not_a_pdf_is_rejected(tmp_path):
    pdf = tmp_path / 'bad.pdf'
    pdf.write_text('<html>oops</html>')
    with pytest.raises(SystemExit):
        cli.main(['--pdf', str(pdf), '--model', 'TWMNH-54HD505', '--power', '505'])


def test_model_power_must_match(tmp_path):
    pdf = fake_pdf(tmp_path)
    with pytest.raises(SystemExit):
        cli.main(['--pdf', str(pdf), '--model', 'TWMNH-54HD500', '--power', '505'])


def test_reject_same_input_and_output(tmp_path):
    pdf = fake_pdf(tmp_path)
    with pytest.raises(SystemExit):
        cli.main(['--pdf', str(pdf), '--model', 'TWMNH-54HD505', '--power', '505',
                  '--json-output', str(pdf)])


def test_missing_local_file_is_rejected(tmp_path):
    with pytest.raises(SystemExit):
        cli.main(['--pdf', str(tmp_path / 'missing.pdf'), '--model', 'TWMNH-54HD505', '--power', '505'])
