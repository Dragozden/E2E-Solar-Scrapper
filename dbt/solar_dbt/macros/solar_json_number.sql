-- Defensive extraction from JSONB normalized_values; bounded integer/fraction digits avoid NUMERIC(14,4) overflow.
-- Unrecognised strings/ranges become NULL instead of aborting the entire dbt build.
-- `object_expr` and `field_name` are constants controlled by our dbt models.
{% macro solar_json_number(object_expr, field_name) -%}
CASE
    WHEN ({{ object_expr }} ->> '{{ field_name }}') ~ '^[+-]?[0-9]{1,8}([.][0-9]{1,4})?$'
      AND LENGTH({{ object_expr }} ->> '{{ field_name }}') <= 15
    THEN ({{ object_expr }} ->> '{{ field_name }}')::NUMERIC(14,4)
    ELSE NULL::NUMERIC(14,4)
END
{%- endmacro %}
