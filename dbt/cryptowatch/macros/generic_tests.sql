{#- Tiny in-house generic tests so the project needs no external packages. -#}

{% test expression_is_true(model, expression, column_name=none, where=none) %}
select * from {{ model }}
where not ({{ expression }})
{% if where %} and ({{ where }}) {% endif %}
{% endtest %}

{% test not_negative(model, column_name) %}
select * from {{ model }} where {{ column_name }} < 0
{% endtest %}

{% test dbt_utils_free_unique_key(model) %}
select coin_id, snapshot_date from {{ model }} group by coin_id, snapshot_date having count(*) > 1
{% endtest %}
