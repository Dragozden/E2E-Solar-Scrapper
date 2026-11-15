"""Offline installer contract: no actual dashboard/app.py is edited."""
import pytest

from scripts.apply_technical_dashboard import patch_app, TAB_BLOCK, TABS_NEW

EXAMPLE = '''from dashboard.db import load_gold_data
if True:
        get_run_quality.clear()
overview_tab, ranking_tab, drops_tab, compare_tab, history_tab, market_tab, quality_tab = st.tabs([
    "Przegląd", "Ranking paneli", "Przeceny", "Porównanie", "Historia produktu",
    "Trendy rynku", "Jakość danych",
])
with quality_tab:
    pass
st.divider()
st.caption(
    "Źródło: publiczne oferty Soltech. Nie są to dane transakcyjne."
)
'''


def test_insert_all_four_points_and_compile():
    result = patch_app(EXAMPLE)
    assert result.count('from dashboard.technical_ui import ') == 1
    assert result.count('        clear_technical_cache()') == 1
    assert result.count(TABS_NEW) == 1
    assert result.count(TAB_BLOCK) == 1
    assert result.index(TAB_BLOCK) > result.index('with quality_tab:')
    assert result.index(TAB_BLOCK) < result.index('st.divider()')
    assert 'Nie są to dane transakcyjne' in result
    compile(result, '<app.py>', 'exec')


def test_patching_twice_is_idempotent():
    result = patch_app(EXAMPLE)
    assert patch_app(result) == result


def test_rejects_unfamiliar_or_incomplete_app():
    with pytest.raises(RuntimeError, match='Unexpected'):
        patch_app('from dashboard.db import load_gold_data\n')
    with pytest.raises(RuntimeError, match='Partial'):
        patch_app(EXAMPLE + 'with technical_tab:\n    pass\n')


def test_other_tabs_are_not_removed():
    result = patch_app(EXAMPLE)
    for label in ('Przegląd', 'Ranking paneli', 'Przeceny', 'Porównanie',
                  'Historia produktu', 'Trendy rynku', 'Jakość danych'):
        assert label in result
