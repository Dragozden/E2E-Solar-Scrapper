-- The new comparison view must NEVER shrink or expand the existing ranking.
WITH row_counts AS (
    SELECT
        (SELECT COUNT(*) FROM {{ ref('current_panel_ranking') }}) AS ranking_rows,
        (SELECT COUNT(*) FROM {{ ref('panel_technical_comparison') }}) AS comparison_rows
)
SELECT * FROM row_counts
WHERE ranking_rows <> comparison_rows
