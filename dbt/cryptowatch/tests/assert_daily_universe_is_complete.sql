select snapshot_date, count(*) as coins from {{ ref('fct_coin_snapshots') }}
group by snapshot_date having count(*) < 450
