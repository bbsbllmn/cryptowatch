-- the first snapshot is the baseline: every coin is "new" then, which must never page anyone
select alert_id from {{ ref('fct_alerts') }}
where rule_code in ('NEW_IN_UNIVERSE', 'NEWLY_TRENDING')
  and snapshot_date < date_add((select min(snapshot_date) from {{ ref('fct_coin_snapshots') }}), interval {{ var('trending_warmup_days') }} day)
