{{ config(
    materialized='incremental', incremental_strategy='insert_overwrite',
    partition_by={'field': 'snapshot_date', 'data_type': 'date'}, cluster_by=['coin_id'],
    partitions=["date('" ~ var('ds') ~ "')"]
) }}
-- One row per coin per day, enriched with its market-cap tier and that tier's alert threshold.
-- Incremental: each run replaces only today's partition; history is untouched and re-runnable.
with s as (
    select * from {{ ref('stg_markets') }}
    {% if is_incremental() %} where snapshot_date = date('{{ var("ds") }}') {% endif %}
),
t as (
    select s.*, th.tier, th.move_threshold_pct, th.min_volume_usd,
           row_number() over (partition by s.snapshot_date, s.coin_id order by th.min_market_cap_usd desc) as rn
    from s
    join {{ ref('alert_thresholds') }} th on coalesce(s.market_cap, 0) >= th.min_market_cap_usd
)
select
    snapshot_date, coin_id, symbol, name, image,
    concat('https://www.coingecko.com/en/coins/', coin_id) as coin_link,
    current_price, market_cap, market_cap_rank, total_volume,
    price_change_pct_1h, price_change_pct_24h, price_change_pct_7d, ath_change_pct, atl_date, last_updated,
    tier, move_threshold_pct, min_volume_usd
from t where rn = 1
