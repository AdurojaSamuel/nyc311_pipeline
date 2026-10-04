#!/usr/bin/env python3
from __future__ import annotations

import argparse, datetime as dt, json, logging, os, shutil, sys, uuid
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from powerbi_duckdb import build_powerbi_db
import requests
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

load_dotenv()

DATASET_ID = "erm2-nwe9"
API_URL = os.getenv("NYC311_API_URL")
APP_TOKEN = os.getenv("SOCRATA_APP_TOKEN")
ROOT = Path(os.getenv("NYC311_ROOT"))
DATA_ROOT = Path(os.getenv("NYC311_DATA_ROOT", ROOT / "data"))

STAGING = DATA_ROOT / "staging"
CURATED = DATA_ROOT / "curated"
META = ROOT / "metadata"
RUNS = META / "runs"
LOGS = ROOT / "logs"
PAGE_SIZE = int(os.getenv("PAGE_SIZE"))
TIMEOUT = int(os.getenv("REQUEST_TIMEOUT_SECONDS"))
KEEP_STAGING = os.getenv("KEEP_STAGING", "0") == "1"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

TIMESTAMP_COLS = ["created_date", "closed_date", "due_date", "resolution_action_updated_date"]

def setup() -> None:
    for p in [STAGING, CURATED, META, RUNS, LOGS]:
        p.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=LOG_LEVEL,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(LOGS / "nyc311_pipeline.log"),
            logging.StreamHandler(sys.stdout),
        ],
    )

def read_json(path: Path, default: Any = None) -> Any:
    return json.loads(path.read_text()) if path.exists() else default

def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True, default=str))
    tmp.replace(path)

def session() -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=7,
        connect=5,
        read=5,
        status=7,
        backoff_factor=1,
        backoff_jitter=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["POST"],
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("https://", adapter)
    s.headers.update({
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "samuel-nyc311-local-parquet/1.0",
    })
    if APP_TOKEN:
        s.headers["X-App-Token"] = APP_TOKEN
    else:
        logging.warning("SOCRATA_APP_TOKEN is not set; expect lower throttling limits.")
    return s

def rows_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = next((payload[k] for k in ("data", "rows", "results") if isinstance(payload.get(k), list)), None)
        if rows is None:
            raise ValueError(f"Unexpected SODA response keys: {sorted(payload.keys())}")
    else:
        raise ValueError(f"Unexpected SODA response type: {type(payload).__name__}")
    if not all(isinstance(r, dict) for r in rows):
        raise ValueError("API returned non-object rows")
    return rows

def post_query(s: requests.Session, soql: str, page: int) -> list[dict[str, Any]]:
    body = {
        "query": soql,
        "page": {"pageNumber": page, "pageSize": PAGE_SIZE},
        "includeSynthetic": False,
        "timeout": TIMEOUT,
    }
    r = s.post(API_URL, json=body, timeout=(30, TIMEOUT))
    r.raise_for_status()
    return rows_from_payload(r.json())

def q(s: str) -> str:
    return s.replace("'", "''")

def socrata_ts(ts: Any) -> str:
    t = pd.to_datetime(ts)
    return t.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]

def normalize(rows: list[dict[str, Any]], run_id: str) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if df.empty:
        return df

    for col in df.columns:
        if df[col].map(lambda x: isinstance(x, (dict, list))).any():
            df[col] = df[col].map(
                lambda x: json.dumps(x, ensure_ascii=False, sort_keys=True) if isinstance(x, (dict, list)) else x
            )

    if "unique_key" not in df or "created_date" not in df:
        raise ValueError("Required columns unique_key/created_date missing from API response.")

    df["unique_key"] = df["unique_key"].astype(str)
    for col in TIMESTAMP_COLS:
        if col in df:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    df = df[df["created_date"].notna()].copy()
    df["_ingested_at"] = pd.Timestamp.utcnow()
    df["_source_dataset"] = DATASET_ID
    df["_run_id"] = run_id
    df["created_year"] = df["created_date"].dt.strftime("%Y")
    df["created_month"] = df["created_date"].dt.strftime("%m")
    return df

def write_stage(df: pd.DataFrame, run_id: str, seq: int) -> Path:
    out = STAGING / run_id / f"part-{seq:06d}.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, engine="pyarrow", compression="zstd", index=False)
    return out

def day_windows(start: dt.date, end: dt.date):
    cur = start
    while cur < end:
        nxt = cur + dt.timedelta(days=1)
        yield cur, min(nxt, end)
        cur = nxt

def fetch_soql_to_stage(soql: str, run_id: str, seq0: int = 0) -> tuple[list[Path], set[tuple[str, str]], int]:
    s = session()
    files, months = [], set()
    page, seq, total = 1, seq0, 0
    while True:
        rows = post_query(s, soql, page)
        if not rows:
            break
        df = normalize(rows, run_id)
        if not df.empty:
            seq += 1
            files.append(write_stage(df, run_id, seq))
            months.update(set(zip(df["created_year"], df["created_month"])))
            total += len(df)
        logging.info("page=%s rows=%s total=%s", page, len(rows), total)
        if len(rows) < PAGE_SIZE:
            break
        page += 1
    return files, months, total

def soql_for_day(start: dt.date, end: dt.date) -> str:
    a, b = f"{start.isoformat()}T00:00:00.000", f"{end.isoformat()}T00:00:00.000"
    return (
        "SELECT * "
        f"WHERE `created_date` >= '{a}' AND `created_date` < '{b}' "
        "ORDER BY `created_date`, `unique_key`"
    )

def soql_incremental(last_created: str, last_key: str) -> str:
    c, k = q(last_created), q(last_key)
    return (
        "SELECT * WHERE "
        f"(`created_date` > '{c}' OR (`created_date` = '{c}' AND `unique_key` > '{k}')) "
        "ORDER BY `created_date`, `unique_key`"
    )

def sql_list(paths: list[Path]) -> str:
    return "[" + ",".join("'" + str(p).replace("'", "''") + "'" for p in paths) + "]"

def merge_month(year: str, month: str, stage_files: list[Path], run_id: str) -> None:
    final_dir = CURATED / f"created_year={year}" / f"created_month={month}"
    existing = list(final_dir.glob("*.parquet")) if final_dir.exists() else []
    inputs = existing + stage_files
    if not inputs:
        return

    tmp_dir = final_dir.with_name(final_dir.name + f".tmp.{run_id}")
    bak_dir = final_dir.with_name(final_dir.name + f".bak.{run_id}")
    shutil.rmtree(tmp_dir, ignore_errors=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_file = tmp_dir / "part-000000.parquet"

    con = duckdb.connect()
    try:
        con.execute(f"""
            COPY (
              SELECT * EXCLUDE(rn)
              FROM (
                SELECT *,
                       row_number() OVER (
                         PARTITION BY unique_key
                         ORDER BY _ingested_at DESC, created_date DESC
                       ) AS rn
                FROM read_parquet({sql_list(inputs)}, union_by_name=true)
              )
              WHERE rn = 1
              ORDER BY created_date, unique_key
            )
            TO '{str(tmp_file).replace("'", "''")}'
            (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 100000);
        """)
    finally:
        con.close()

    try:
        if final_dir.exists():
            shutil.rmtree(bak_dir, ignore_errors=True)
            final_dir.rename(bak_dir)
        tmp_dir.rename(final_dir)
        shutil.rmtree(bak_dir, ignore_errors=True)
    except Exception:
        if bak_dir.exists() and not final_dir.exists():
            bak_dir.rename(final_dir)
        raise

def high_watermark_from_dataset() -> dict[str, str] | None:
    files = list(CURATED.glob("created_year=*/created_month=*/*.parquet"))
    if not files:
        return None
    con = duckdb.connect()
    try:
        row = con.execute(f"""
            SELECT created_date, unique_key
            FROM read_parquet({sql_list(files)}, union_by_name=true)
            WHERE created_date IS NOT NULL
            ORDER BY created_date DESC, unique_key DESC
            LIMIT 1
        """).fetchone()
    finally:
        con.close()
    return {"created_date": socrata_ts(row[0]), "unique_key": str(row[1])} if row else None

def row_counts() -> dict[str, int]:
    files = list(CURATED.glob("created_year=*/created_month=*/*.parquet"))
    if not files:
        return {"rows": 0, "distinct_unique_key": 0, "duplicates": 0}
    con = duckdb.connect()
    try:
        rows, distinct_keys = con.execute(f"""
            SELECT count(*), count(DISTINCT unique_key)
            FROM read_parquet({sql_list(files)}, union_by_name=true)
        """).fetchone()
    finally:
        con.close()
    return {"rows": rows, "distinct_unique_key": distinct_keys, "duplicates": rows - distinct_keys}

def commit_run(
    run_id: str,
    files: list[Path],
    months: set[tuple[str, str]],
    mode: str,
    total: int,
) -> None:
    for year, month in sorted(months):
        month_files: list[Path] = []

        for f in files:
            # Cheap metadata scan of stage file to see whether this month is present.
            # Avoid putting quote-escaping logic inside an f-string expression.
            con = duckdb.connect()
            try:
                result = con.execute(
                    f"""
                    SELECT count(*)
                    FROM read_parquet({sql_list([f])}, union_by_name=true)
                    WHERE created_year = ? AND created_month = ?
                    """,
                    [year, month],
                ).fetchone()

                n = int(result[0]) if result is not None else 0
            finally:
                con.close()

            if n:
                month_files.append(f)

        merge_month(year, month, month_files, run_id)

    wm = high_watermark_from_dataset()
    counts = row_counts()

    state = {
        "dataset": DATASET_ID,
        "api_url": API_URL,
        "last_successful_run_id": run_id,
        "last_successful_mode": mode,
        "updated_at_utc": dt.datetime.utcnow().isoformat() + "Z",
        "high_watermark": wm,
        **counts,
    }

    write_json_atomic(META / "state.json", state)
    write_json_atomic(
        RUNS / f"{run_id}.json",
        {
            "status": "success",
            "mode": mode,
            "staged_rows": total,
            **state,
        },
    )

    if not KEEP_STAGING:
        shutil.rmtree(STAGING / run_id, ignore_errors=True)

def run_full(start: dt.date, end: dt.date) -> None:
    run_id = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    all_files, all_months, total, seq = [], set(), 0, 0
    for a, b in day_windows(start, end):
        logging.info("full window %s to %s", a, b)
        files, months, n = fetch_soql_to_stage(soql_for_day(a, b), run_id, seq)
        seq += len(files)
        all_files.extend(files); all_months |= months; total += n
        write_json_atomic(RUNS / f"{run_id}.checkpoint.json", {
            "status": "running", "last_window_start": str(a), "staged_rows": total
        })
    commit_run(run_id, all_files, all_months, "full", total)

def run_incremental() -> None:
    state = read_json(META / "state.json")
    if not state or not state.get("high_watermark"):
        raise SystemExit("No high-watermark found. Run full load first.")
    wm = state["high_watermark"]
    run_id = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    files, months, total = fetch_soql_to_stage(soql_incremental(wm["created_date"], wm["unique_key"]), run_id)
    if total == 0:
        write_json_atomic(RUNS / f"{run_id}.json", {"status": "success", "mode": "incremental", "staged_rows": 0})
        logging.info("No new rows.")
        return
    commit_run(run_id, files, months, "incremental", total)

def run_range(start: dt.date, end: dt.date) -> None:
    run_id = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    all_files, all_months, total, seq = [], set(), 0, 0
    for a, b in day_windows(start, end):
        files, months, n = fetch_soql_to_stage(soql_for_day(a, b), run_id, seq)
        seq += len(files)
        all_files.extend(files); all_months |= months; total += n
    commit_run(run_id, all_files, all_months, "range", total)

def main():
    setup()
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("full")
    f.add_argument("--start-date", default=os.getenv("START_DATE", "2020-01-01"))
    f.add_argument("--end-date", default=None, help="exclusive; default tomorrow UTC")
    sub.add_parser("incremental")
    r = sub.add_parser("range")
    r.add_argument("--start-date", required=True)
    r.add_argument("--end-date", required=True, help="exclusive")
    sub.add_parser("validate")
    args = p.parse_args()

    try:
        if args.cmd == "full":
            end = dt.date.fromisoformat(args.end_date) if args.end_date else dt.datetime.utcnow().date() + dt.timedelta(days=1)
            run_full(dt.date.fromisoformat(args.start_date), end)
        elif args.cmd == "incremental":
            run_incremental()
        elif args.cmd == "range":
            run_range(dt.date.fromisoformat(args.start_date), dt.date.fromisoformat(args.end_date))
        elif args.cmd == "validate":
            print(json.dumps({"state": read_json(META / "state.json"), "counts": row_counts()}, indent=2, default=str))
    except Exception as e:
        logging.exception("Pipeline failed")
        raise

if __name__ == "__main__":
    main()