select a.alert_id
from {{ ref('fct_alerts') }} a
join {{ ref('alert_thresholds') }} th on th.tier = a.tier
where a.rule_code = 'PRICE_MOVE'
  and (abs(a.price_change_pct_24h) < th.move_threshold_pct or a.total_volume < th.min_volume_usd)
