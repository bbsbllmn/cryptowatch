-- Typed, de-duplicated daily coin snapshot. The raw table is partitioned by snapshot_date, so a
-- reload of one day replaces exactly that day; the QUALIFY is belt-and-braces for double loads.
select
    snapshot_date, fetched_at, coin_id, symbol, name, image,
    current_price, market_cap, market_cap_rank, total_volume,
    price_change_pct_1h, price_change_pct_24h, price_change_pct_7d,
    ath_change_pct, atl_date, last_updated
from {{ source('crypto_raw', 'raw_markets') }}
where current_price is not null and current_price > 0
qualify row_number() over (partition by snapshot_date, coin_id order by fetched_at desc) = 1
