select snapshot_date, coin_id, symbol, name, thumb, trend_rank
from {{ source('crypto_raw', 'raw_trending') }}
qualify row_number() over (partition by snapshot_date, coin_id order by fetched_at desc) = 1
