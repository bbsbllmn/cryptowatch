select a.alert_id from {{ ref('fct_alerts') }} a
where a.is_repeat and not exists (
    select 1 from {{ ref('fct_alerts') }} b
    where b.coin_id = a.coin_id and b.rule_code = a.rule_code and b.snapshot_date < a.snapshot_date)
