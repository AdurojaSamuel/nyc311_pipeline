#!/usr/bin/env python3
"""Build the DuckDB serving layer used by the Power BI dashboard.

The Parquet lake remains the system of record.  This module rebuilds a compact
DuckDB database from curated Parquet only after the ingestion/merge phase has
completed successfully.  Power BI should connect to this database through the
DuckDB ODBC driver and import the prepared tables instead of repeating the
heavy M transformations.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(os.getenv("NYC311_ROOT", Path(__file__).resolve().parents[1]))
DATA_ROOT = Path(os.getenv("NYC311_DATA_ROOT", ROOT / "data"))
CURATED = DATA_ROOT / "curated"
DEFAULT_DB = Path(os.getenv("NYC311_POWERBI_DB", DATA_ROOT / "powerbi" / "nyc311_powerbi.duckdb"))


def _sql_path(path: Path) -> str:
    return str(path).replace("\\", "/").replace("'", "''")


def _inventory(files: list[Path], curated: Path) -> pd.DataFrame:
    rows = []
    for f in files:
        rel = f.relative_to(curated)
        parts = rel.parts
        year = next((p.split("=", 1)[1] for p in parts if p.startswith("created_year=")), None)
        month = next((p.split("=", 1)[1] for p in parts if p.startswith("created_month=")), None)
        rows.append(
            {
                "source_file_path": str(rel).replace("/", "\\"),
                "source_file_abs": str(f.resolve()).replace("\\", "/"),
                "partition_year": int(year) if year else None,
                "partition_month": int(month) if month else None,
                "source_file_modified_ts": pd.Timestamp(f.stat().st_mtime, unit="s"),
            }
        )
    return pd.DataFrame(rows)


def build_powerbi_db(curated: Path = CURATED, db_path: Path = DEFAULT_DB) -> Path:
    files = sorted(curated.glob("created_year=*/created_month=*/*.parquet"))
    if not files:
        raise RuntimeError(f"No curated Parquet files found under {curated}")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = db_path.with_suffix(db_path.suffix + ".tmp")
    tmp_path.unlink(missing_ok=True)

    parquet_glob = _sql_path(curated / "created_year=*" / "created_month=*" / "*.parquet")
    inventory = _inventory(files, curated)

    con = duckdb.connect(str(tmp_path))
    try:
        con.execute("PRAGMA threads = 4")
        con.register("file_inventory_df", inventory)

        # One scan-friendly staging table. filename=true gives lineage for
        # Pipeline Files and Data Quality without Power Query Folder.Files.
        con.execute(f"""
            CREATE TABLE raw_311 AS
            SELECT *
            FROM read_parquet(
                '{parquet_glob}',
                hive_partitioning = true,
                union_by_name = true,
                filename = true
            );
        """)

        con.execute("""
            CREATE TABLE service_requests AS
            WITH base AS (
                SELECT
                    try_cast(created_date AS TIMESTAMP) AS created_ts,
                    try_cast(closed_date AS TIMESTAMP) AS closed_ts,
                    CASE WHEN agency IS NULL OR trim(cast(agency AS VARCHAR)) = ''
                         THEN 'Unspecified' ELSE upper(trim(cast(agency AS VARCHAR))) END AS agency,
                    CASE WHEN complaint_type IS NULL OR trim(cast(complaint_type AS VARCHAR)) = ''
                         THEN 'Unspecified' ELSE trim(cast(complaint_type AS VARCHAR)) END AS complaint_type,
                    CASE WHEN descriptor IS NULL OR trim(cast(descriptor AS VARCHAR)) = ''
                         THEN 'Unspecified' ELSE trim(cast(descriptor AS VARCHAR)) END AS descriptor,
                    upper(coalesce(trim(cast(borough AS VARCHAR)), '')) AS borough_raw,
                    CASE WHEN community_board IS NULL OR trim(cast(community_board AS VARCHAR)) = ''
                         THEN '0 Unspecified' ELSE trim(cast(community_board AS VARCHAR)) END AS community_board,
                    upper(coalesce(trim(cast(open_data_channel_type AS VARCHAR)), '')) AS channel_raw,
                    CASE WHEN status IS NULL OR trim(cast(status AS VARCHAR)) = ''
                         THEN 'Unspecified' ELSE trim(cast(status AS VARCHAR)) END AS status
                FROM raw_311
                WHERE try_cast(created_date AS TIMESTAMP) IS NOT NULL
            ),
            stamped AS (
                SELECT *, max(created_ts) OVER () AS as_of_ts
                FROM base
            ),
            metrics AS (
                SELECT *,
                    CASE WHEN upper(status) = 'CLOSED' THEN 1 ELSE 0 END AS is_closed,
                    CASE
                        WHEN upper(status) = 'CLOSED'
                         AND closed_ts IS NOT NULL
                         AND closed_ts >= created_ts
                         AND closed_ts <= created_ts + INTERVAL 730 DAY
                        THEN round(date_diff('second', created_ts, closed_ts) / 3600.0, 1)
                        ELSE NULL
                    END AS resolution_hours,
                    CASE WHEN upper(status) <> 'CLOSED'
                         THEN date_diff('day', created_ts, as_of_ts)
                         ELSE NULL END AS open_age_days
                FROM stamped
            ),
            classified AS (
                SELECT *,
                    CASE
                        WHEN upper(complaint_type) LIKE 'NOISE%' OR upper(complaint_type) = 'ILLEGAL FIREWORKS'
                            THEN 'Noise'
                        WHEN agency = 'HPD' THEN 'Housing Conditions'
                        WHEN upper(complaint_type) IN (
                            'ILLEGAL PARKING','BLOCKED DRIVEWAY','ABANDONED VEHICLE',
                            'DERELICT VEHICLE','DERELICT VEHICLES','BROKEN PARKING METER','ABANDONED BIKE'
                        ) OR agency = 'TLC' OR upper(complaint_type) LIKE '%TAXI%'
                          OR upper(complaint_type) LIKE 'FOR HIRE VEHICLE%'
                            THEN 'Parking & Vehicles'
                        WHEN agency = 'DHS' OR upper(complaint_type) LIKE 'HOMELESS%'
                          OR upper(complaint_type) IN ('ENCAMPMENT','PANHANDLING')
                            THEN 'Homelessness & Street Conditions'
                        WHEN agency = 'DSNY'
                          OR regexp_matches(upper(complaint_type),
                             'DIRTY|SANITA|DUMPING|LITTER|GRAFFITI|RODENT|COLLECTION|DISPOSAL|DUMPSTER|DEAD ANIMAL|WASTE')
                            THEN 'Sanitation & Cleanliness'
                        WHEN agency = 'DPR' OR upper(complaint_type) LIKE '%TREE%'
                            THEN 'Parks & Trees'
                        WHEN agency = 'DOT'
                          OR regexp_matches(upper(complaint_type),
                             '^(STREET|SIDEWALK|TRAFFIC|HIGHWAY|CURB|BRIDGE|BUS STOP)')
                            THEN 'Streets & Transportation'
                        WHEN agency = 'DEP' THEN 'Water, Sewer & Environment'
                        WHEN agency = 'DOB' THEN 'Buildings & Construction'
                        WHEN agency = 'DOHMH' THEN 'Public Health'
                        WHEN agency = 'NYPD' THEN 'Public Safety & Quality of Life'
                        WHEN agency IN ('DCWP','DCA') THEN 'Consumer Protection'
                        ELSE 'Other City Services'
                    END AS complaint_category
                FROM metrics
            )
            SELECT
                cast(created_ts AS DATE) AS created_date,
                extract(hour FROM created_ts)::BIGINT AS created_hour,
                cast(closed_ts AS DATE) AS closed_date,
                agency,
                complaint_type,
                descriptor,
                complaint_category,
                CASE WHEN borough_raw IN ('BRONX','BROOKLYN','MANHATTAN','QUEENS','STATEN ISLAND')
                     THEN CASE borough_raw
                         WHEN 'BRONX' THEN 'Bronx'
                         WHEN 'BROOKLYN' THEN 'Brooklyn'
                         WHEN 'MANHATTAN' THEN 'Manhattan'
                         WHEN 'QUEENS' THEN 'Queens'
                         WHEN 'STATEN ISLAND' THEN 'Staten Island'
                     END ELSE 'Unspecified' END AS borough,
                community_board,
                CASE WHEN channel_raw IN ('ONLINE','PHONE','MOBILE','OTHER')
                     THEN CASE channel_raw
                         WHEN 'ONLINE' THEN 'Online'
                         WHEN 'PHONE' THEN 'Phone'
                         WHEN 'MOBILE' THEN 'Mobile'
                         WHEN 'OTHER' THEN 'Other'
                     END ELSE 'Unknown' END AS channel,
                status,
                is_closed,
                resolution_hours,
                CASE
                    WHEN resolution_hours IS NULL THEN NULL
                    WHEN resolution_hours <= 24 THEN '< 1 day'
                    WHEN resolution_hours <= 72 THEN '1-3 days'
                    WHEN resolution_hours <= 168 THEN '3-7 days'
                    WHEN resolution_hours <= 720 THEN '7-30 days'
                    ELSE '> 30 days'
                END AS resolution_bucket,
                CASE
                    WHEN resolution_hours IS NULL THEN NULL
                    WHEN resolution_hours <= 24 THEN 1
                    WHEN resolution_hours <= 72 THEN 2
                    WHEN resolution_hours <= 168 THEN 3
                    WHEN resolution_hours <= 720 THEN 4
                    ELSE 5
                END::BIGINT AS resolution_bucket_order,
                open_age_days::BIGINT AS open_age_days,
                CASE
                    WHEN open_age_days IS NULL THEN NULL
                    WHEN open_age_days <= 7 THEN '0-7 days'
                    WHEN open_age_days <= 30 THEN '8-30 days'
                    WHEN open_age_days <= 90 THEN '31-90 days'
                    WHEN open_age_days <= 365 THEN '91-365 days'
                    ELSE '> 1 year'
                END AS backlog_age_bucket,
                CASE
                    WHEN open_age_days IS NULL THEN NULL
                    WHEN open_age_days <= 7 THEN 1
                    WHEN open_age_days <= 30 THEN 2
                    WHEN open_age_days <= 90 THEN 3
                    WHEN open_age_days <= 365 THEN 4
                    ELSE 5
                END::BIGINT AS backlog_age_bucket_order
            FROM classified;
        """)

        con.execute("""
            CREATE TABLE agency AS
            WITH x AS (
                SELECT
                    CASE WHEN agency IS NULL OR trim(cast(agency AS VARCHAR)) = ''
                         THEN 'Unspecified' ELSE trim(cast(agency AS VARCHAR)) END AS agency,
                    CASE WHEN agency_name IS NOT NULL AND trim(cast(agency_name AS VARCHAR)) <> ''
                         THEN trim(cast(agency_name AS VARCHAR))
                         WHEN agency IS NULL OR trim(cast(agency AS VARCHAR)) = ''
                         THEN 'Unspecified' ELSE trim(cast(agency AS VARCHAR)) END AS agency_name
                FROM raw_311
            )
            SELECT agency, max(agency_name) AS agency_name
            FROM x GROUP BY agency;
        """)

        con.execute("""
            CREATE TABLE community_board AS
            WITH x AS (
                SELECT
                    CASE WHEN community_board IS NULL OR trim(cast(community_board AS VARCHAR)) = ''
                         THEN '0 Unspecified' ELSE trim(cast(community_board AS VARCHAR)) END AS community_board,
                    CASE WHEN try_cast(latitude AS DOUBLE) BETWEEN 40.4 AND 41.0
                         THEN try_cast(latitude AS DOUBLE) END AS latitude,
                    CASE WHEN try_cast(longitude AS DOUBLE) BETWEEN -74.3 AND -73.6
                         THEN try_cast(longitude AS DOUBLE) END AS longitude
                FROM raw_311
            ),
            g AS (
                SELECT community_board, avg(latitude) AS latitude, avg(longitude) AS longitude
                FROM x GROUP BY community_board
            )
            SELECT
                community_board,
                CASE
                    WHEN regexp_matches(community_board, '^[0-9]{2} ')
                    THEN CASE upper(substr(community_board, 4))
                        WHEN 'BRONX' THEN 'Bronx'
                        WHEN 'BROOKLYN' THEN 'Brooklyn'
                        WHEN 'MANHATTAN' THEN 'Manhattan'
                        WHEN 'QUEENS' THEN 'Queens'
                        WHEN 'STATEN ISLAND' THEN 'Staten Island'
                        ELSE substr(community_board, 4)
                    END || ' CB ' || substr(community_board, 1, 2)
                    WHEN community_board LIKE 'Unspecified %'
                    THEN substr(community_board, 13) || ' - Unspecified'
                    ELSE 'Unspecified'
                END AS board_name,
                CASE
                    WHEN upper(community_board) LIKE '%BRONX%' THEN 'Bronx'
                    WHEN upper(community_board) LIKE '%BROOKLYN%' THEN 'Brooklyn'
                    WHEN upper(community_board) LIKE '%MANHATTAN%' THEN 'Manhattan'
                    WHEN upper(community_board) LIKE '%QUEENS%' THEN 'Queens'
                    WHEN upper(community_board) LIKE '%STATEN ISLAND%' THEN 'Staten Island'
                    ELSE 'Unspecified'
                END AS board_borough,
                latitude,
                longitude
            FROM g;
        """)

        con.execute("""
            CREATE TABLE data_quality AS
            SELECT
                make_date(try_cast(created_year AS INTEGER), try_cast(created_month AS INTEGER), 1) AS month_start,
                count(*) AS row_count,
                count(*) FILTER (
                    WHERE upper(trim(coalesce(cast(borough AS VARCHAR), ''))) NOT IN
                    ('BRONX','BROOKLYN','MANHATTAN','QUEENS','STATEN ISLAND')
                ) AS missing_borough,
                count(*) FILTER (
                    WHERE try_cast(latitude AS DOUBLE) IS NULL OR try_cast(longitude AS DOUBLE) IS NULL
                ) AS missing_geo,
                count(*) FILTER (
                    WHERE status = 'Closed' AND try_cast(closed_date AS TIMESTAMP) IS NULL
                ) AS closed_without_date,
                count(*) FILTER (
                    WHERE try_cast(created_date AS TIMESTAMP) IS NOT NULL
                      AND try_cast(closed_date AS TIMESTAMP) IS NOT NULL
                      AND try_cast(closed_date AS TIMESTAMP) < try_cast(created_date AS TIMESTAMP)
                ) AS negative_duration,
                count(*) FILTER (WHERE try_cast(created_date AS TIMESTAMP) IS NULL) AS invalid_created_date,
                0::BIGINT AS rescued_rows,
                count(DISTINCT filename) AS source_files
            FROM raw_311
            GROUP BY 1
            ORDER BY 1;
        """)

        con.execute("""
            CREATE TABLE file_inventory AS
            SELECT * FROM file_inventory_df;
        """)

        con.execute("""
            CREATE TABLE pipeline_files AS
            WITH f AS (
                SELECT
                    replace(filename, '\\', '/') AS source_file_abs,
                    try_cast(created_year AS INTEGER) AS partition_year,
                    try_cast(created_month AS INTEGER) AS partition_month,
                    count(*) AS row_count,
                    max(try_cast(created_date AS TIMESTAMP)) AS max_created_ts
                FROM raw_311
                GROUP BY 1,2,3
            )
            SELECT
                i.source_file_path,
                regexp_extract(replace(i.source_file_path, '\\', '/'), '[^/]+$', 0) AS source_file_name,
                f.partition_year,
                f.partition_month,
                NULL::TIMESTAMP AS ingestion_ts,
                NULL::DATE AS ingestion_date,
                i.source_file_modified_ts,
                f.row_count,
                0::BIGINT AS rescued_rows,
                f.max_created_ts
            FROM f
            LEFT JOIN file_inventory i USING (source_file_abs)
            ORDER BY f.partition_year, f.partition_month, i.source_file_path;
        """)

        # raw_311 is an implementation detail; Power BI only needs prepared tables.
        con.execute("DROP TABLE file_inventory")
        con.execute("DROP TABLE raw_311")
        con.execute("CHECKPOINT")
    finally:
        con.close()

    # Atomic publication prevents Power BI from seeing a half-built database.
    # The replace can fail if another process currently holds the DuckDB file;
    # schedule the Power BI refresh after the pipeline build has completed.
    os.replace(tmp_path, db_path)
    return db_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--curated", type=Path, default=CURATED)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args()
    path = build_powerbi_db(args.curated, args.db)
    print(path)


if __name__ == "__main__":
    main()
