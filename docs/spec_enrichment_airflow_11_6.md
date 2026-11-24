# Airflow — technical enrichment pilot

The existing batch script retains responsibility for selecting previously unsaved HTML specifications, recording attempts, validating data and saving each product atomically. Airflow only orchestrates a bounded invocation, with a plan, optional live run, then coverage checks. It uses the same project virtualenv as `solar_el_pipeline`. No new data source or PDF imports are introduced.

| Configuration | Plan | Product requests | Product writes |
| --- | --- | --- | --- |
| plan (default) | yes | no | no |
| preview | yes | up to limit | no |
| write | yes | up to limit | yes |

The two explicit confirmations are operator attestations, not locks. The existing batch has a local exclusive lock in `backups/.panel_spec_batch.lock`, which only protects processes sharing that directory. Manual operation must exclude concurrent catalog and PDF scraping. The scheduled pipeline and watchdog remain unchanged. Before a production schedule, implement cross-process coordination and validate runtime mounts, access policies, stop-on-error, alerting and retention.

All tasks have zero retries, and the DAG has no schedule or catchup and at most one active run. A failed subprocess causes the task to fail and prevents downstream validation. Per-product committed data is not rolled back by later errors. Inspect status and do not blindly retry a failed network run. Timeouts may leave stale lock files or child browser processes; inspect before resuming. The final checks read coverage and status rather than building views, so they avoid schema changes and do not substitute for a full dbt build.
