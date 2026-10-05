# Power BI DuckDB serving layer

This branch keeps the curated partitioned Parquet dataset as the durable source
and builds a Power BI-ready DuckDB database after each successful pipeline run.

## Output database

By default:

`<NYC311_DATA_ROOT>/nyc311_powerbi.duckdb`

Override it with `NYC311_POWERBI_DB`.

Prepared tables:

- `service_requests`
- `agency`
- `community_board`
- `data_quality`
- `pipeline_files`

## Build manually

From the repository root:

```powershell
python src/powerbi_duckdb.py
```

Normal `full`, `range`, and `incremental` pipeline runs rebuild the serving
database after the curated Parquet commit succeeds. Incremental runs with no new
rows also rebuild it, which makes the serving database self-healing after schema
changes or deletion.

## Power BI connection

Install the 64-bit DuckDB ODBC driver on the Windows machine running Power BI
Desktop and the gateway. Create a 64-bit System DSN pointing to the generated
DuckDB file, preferably read-only for Power BI.

In Power BI, replace the Parquet staging query and downstream transformation
queries with imports of the five prepared DuckDB tables. Keep the existing
relationships, DAX measures, visuals, and incremental-refresh policy initially.

For `service_requests`, apply the Power BI incremental-refresh predicate to the
DateTime column `created_ts`:

```text
created_ts >= RangeStart
created_ts <  RangeEnd
```

Keep `created_date` for reporting and date-model relationships; `created_ts` is
the technical timestamp used for partition boundaries.

## Scheduling

Do not refresh Power BI while the builder is replacing the DuckDB file. The
builder writes a temporary database and atomically replaces the published file
only after all prepared tables are complete. Schedule the Power BI refresh after
the ingestion job has finished successfully.

## First benchmark

Before changing the report model further, benchmark:

1. one-year import through DuckDB/ODBC;
2. full retained-history initial refresh;
3. one-month incremental refresh.

This isolates source/ODBC performance from report/DAX performance.
