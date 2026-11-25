{{ config(materialized='table', partition_by={'field': 'snapshot_date', 'data_type': 'date'}, cluster_by=['rule_code']) }}
-- Every alert the rules would raise, for every day in history, derived purely from the snapshots
-- (idempotent: rebuilding gives the same answer). `is_repeat` marks re-fires of the same coin+rule within
-- `repeat_days`; the notifier skips repeats so analysts are not paged about the same pump every morning.
--
-- Rules
--   PRICE_MOVE       |24h change| >= tier threshold AND 24h volume >= tier floor (thin markets are noise)
--   NEWLY_TRENDING   on the trending list today, absent for the previous `trending_lookback_days`
--   NEW_IN_UNIVERSE  first time we see the coin in the top 500 (HIGH confidence when its all-time low is
--                    < 30 days old, i.e. likely a genuinely new listing)
-- Cold start: trending/new rules stay silent until `trending_warmup_days` of history exist, otherwise the
-- first run would flag all 500 coins as "new".
with s as (select * from {{ ref('fct_coin_snapshots') }}),

scored as (
    select s.*,
        avg(price_change_pct_24h)         over w as mean_30d,
        stddev_samp(price_change_pct_24h) over w as sd_30d,
        count(price_change_pct_24h)       over w as n_30d
    from s
    window w as (partition by coin_id order by snapshot_date rows between {{ var('z_window') }} preceding and 1 preceding)
),

enriched as (
    select *,
        case when n_30d >= {{ var('z_min_obs') }} and sd_30d > 0
             then (price_change_pct_24h - mean_30d) / sd_30d end as z_24h
    from scored
),

meta as (select min(snapshot_date) as baseline_date from s),
first_seen as (select coin_id, min(snapshot_date) as first_seen_date from s group by coin_id),

moves as (
    select e.*, 'PRICE_MOVE' as rule_code,
        case when price_change_pct_24h > 0 then 'UP' else 'DOWN' end as direction,
        case when abs(price_change_pct_24h) >= 1.5 * move_threshold_pct or coalesce(abs(z_24h), 0) >= 4 then 'HIGH' else 'MEDIUM' end as severity,
        cast(least(100, round(100 * abs(price_change_pct_24h) / (2 * move_threshold_pct))) as int64) as priority_score,
        cast(null as int64) as trend_rank
    from enriched e
    where abs(price_change_pct_24h) >= move_threshold_pct and total_volume >= min_volume_usd
),

trending_today as (
    select t.snapshot_date, t.coin_id, t.trend_rank
    from {{ ref('stg_trending') }} t
    where not exists (
        select 1 from {{ ref('stg_trending') }} p
        where p.coin_id = t.coin_id
          and p.snapshot_date between date_sub(t.snapshot_date, interval {{ var('trending_lookback_days') }} day)
                                  and date_sub(t.snapshot_date, interval 1 day))
),

newly_trending as (
    select e.*, 'NEWLY_TRENDING' as rule_code, 'NONE' as direction,
        case when t.trend_rank <= 2 then 'MEDIUM' else 'LOW' end as severity,
        cast(greatest(10, 60 - 3 * t.trend_rank) as int64) as priority_score, t.trend_rank
    from enriched e
    join trending_today t on t.coin_id = e.coin_id and t.snapshot_date = e.snapshot_date
    cross join meta
    where date_diff(e.snapshot_date, meta.baseline_date, day) >= {{ var('trending_warmup_days') }}
),

new_coins as (
    select e.*, 'NEW_IN_UNIVERSE' as rule_code, 'NONE' as direction,
        case when e.atl_date >= timestamp_sub(timestamp(e.snapshot_date), interval 30 day) then 'HIGH' else 'MEDIUM' end as severity,
        case when e.atl_date >= timestamp_sub(timestamp(e.snapshot_date), interval 30 day) then 70 else 50 end as priority_score,
        cast(null as int64) as trend_rank
    from enriched e
    join first_seen f on f.coin_id = e.coin_id and f.first_seen_date = e.snapshot_date
    cross join meta
    where e.snapshot_date > meta.baseline_date
),

unioned as (
    select * from moves union all select * from newly_trending union all select * from new_coins
),

flagged as (
    select u.*,
        lag(snapshot_date) over (partition by coin_id, rule_code order by snapshot_date) as prev_alert_date
    from unioned u
)

select
    to_hex(md5(concat(coin_id, '|', rule_code, '|', cast(snapshot_date as string)))) as alert_id,
    snapshot_date, coin_id, symbol, name, image, coin_link,
    rule_code, direction, severity, priority_score,
    current_price, price_change_pct_24h, price_change_pct_7d, market_cap, market_cap_rank, total_volume,
    tier, move_threshold_pct, round(z_24h, 2) as z_24h, ath_change_pct, trend_rank, last_updated,
    coalesce(date_diff(snapshot_date, prev_alert_date, day) <= {{ var('repeat_days') }}, false) as is_repeat
from flagged
