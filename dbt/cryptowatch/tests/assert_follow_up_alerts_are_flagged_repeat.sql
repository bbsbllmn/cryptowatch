-- the inverse guard: a second alert for the same coin + rule within repeat_days MUST be marked is_repeat,
-- otherwise the notifier would page people about the same event every morning
select a.alert_id from {{ ref('fct_alerts') }} a
where not a.is_repeat and exists (
    select 1 from {{ ref('fct_alerts') }} b
    where b.coin_id = a.coin_id and b.rule_code = a.rule_code
      and b.snapshot_date < a.snapshot_date
      and date_diff(a.snapshot_date, b.snapshot_date, day) <= {{ var('repeat_days') }})
