"""Live, aggregated NYC 311 request data loaders shared by the dashboards."""
from __future__ import annotations

import logging
import os
from datetime import UTC, datetime, timedelta

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

LOGGER = logging.getLogger(__name__)
API_URL = os.getenv(
    "NYC311_API_URL",
    "https://data.cityofnewyork.us/resource/erm2-nwe9.json",
)
APP_TOKEN = os.getenv("SOCRATA_APP_TOKEN")
BOROUGH_NORMALIZATION = {
    "": "UNKNOWN",
    "UNSPECIFIED": "UNSPECIFIED",
}


def _session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    if APP_TOKEN:
        session.headers["X-App-Token"] = APP_TOKEN
    return session


def _get_rows(params: dict[str, str]) -> list[dict[str, str]]:
    response = _session().get(API_URL, params=params, timeout=(10, 90))
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise RuntimeError(f"NYC Open Data returned an unexpected response: {payload!r}")
    return payload


def refresh_dashboard_data(
    frame: pd.DataFrame,
    *,
    lookback_days: int = 90,
) -> tuple[pd.DataFrame, str]:
    """Refresh recent opened/closed daily borough totals using NYC Open Data."""
    now = datetime.now(UTC)
    start = (now - timedelta(days=lookback_days)).date()
    start_text = start.isoformat()
    date_filter = f'"{start_text}T00:00:00"'
    grouping = "date_trunc_ymd(created_date),borough"
    opened_rows = _get_rows(
        {
            "$select": "date_trunc_ymd(created_date) as date,borough,count(*) as opened",
            "$where": f"created_date >= {date_filter}",
            "$group": grouping,
            "$order": "date",
            "$limit": "50000",
        }
    )

    opened = pd.DataFrame(opened_rows)
    if opened.empty:
        raise RuntimeError("NYC Open Data returned no recent created requests.")
    opened["date"] = pd.to_datetime(opened["date"], errors="raise").dt.normalize()
    opened["borough"] = opened["borough"].fillna("").astype(str).str.strip().str.upper()
    opened["borough"] = opened["borough"].replace(BOROUGH_NORMALIZATION)
    opened["opened"] = pd.to_numeric(opened["opened"], errors="raise").astype("int64")
    current_max = opened["date"].max()

    closed_rows = _get_rows(
        {
            "$select": "date_trunc_ymd(closed_date) as date,borough,count(*) as closed",
            "$where": f"closed_date >= {date_filter} AND closed_date < '{(current_max + pd.Timedelta(days=1)).date()}T00:00:00'",
            "$group": "date_trunc_ymd(closed_date),borough",
            "$order": "date",
            "$limit": "50000",
        }
    )
    closed = pd.DataFrame(closed_rows)
    if not closed.empty:
        closed["date"] = pd.to_datetime(closed["date"], errors="raise").dt.normalize()
        closed["borough"] = closed["borough"].fillna("").astype(str).str.strip().str.upper()
        closed["borough"] = closed["borough"].replace(BOROUGH_NORMALIZATION)
        closed["closed"] = pd.to_numeric(closed["closed"], errors="raise").astype("int64")

    fresh = opened.merge(closed, on=["date", "borough"], how="outer").fillna(
        {"opened": 0, "closed": 0}
    )
    fresh[["opened", "closed"]] = fresh[["opened", "closed"]].astype("int64")
    cutoff = pd.Timestamp(start)
    retained = frame.loc[frame["date"] < cutoff].copy()
    result = pd.concat([retained, fresh], ignore_index=True)
    result["date"] = pd.to_datetime(result["date"]).dt.normalize()
    result = (
        result.groupby(["date", "borough"], as_index=False)[["opened", "closed"]]
        .sum()
        .sort_values(["date", "borough"])
        .reset_index(drop=True)
    )
    source_updated = current_max.strftime("%Y-%m-%d")
    LOGGER.info("Refreshed NYC 311 dashboard data through %s.", source_updated)
    return result, source_updated


def refresh_dashboard_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Reticulate-friendly wrapper for refreshing the existing dashboard frame."""
    refreshed, _ = refresh_dashboard_data(frame)
    return refreshed


def load_recent_hourly_requests(
    *,
    borough: str = "ALL",
    days: int = 120,
) -> tuple[pd.DataFrame, str]:
    """Fetch the current hourly service-request proxy, grouped at source."""
    start = (datetime.now(UTC) - timedelta(days=days)).date().isoformat()
    where = f'created_date >= "{start}T00:00:00"'
    if borough != "ALL":
        where += f" AND upper(trim(borough)) = '{borough.replace(chr(39), chr(39) * 2)}'"

    rows = _get_rows(
        {
            "$select": "date_trunc_ymd(created_date) as day,date_extract_hh(created_date) as hour,borough,count(*) as requests",
            "$where": where,
            "$group": "date_trunc_ymd(created_date),date_extract_hh(created_date),borough",
            "$order": "day,hour",
            "$limit": "50000",
        }
    )
    result = pd.DataFrame(rows)
    if result.empty:
        raise RuntimeError("NYC Open Data returned no hourly request data for the selected period.")
    result["day"] = pd.to_datetime(result["day"], errors="raise").dt.normalize()
    result["hour"] = pd.to_numeric(result["hour"], errors="raise").astype(int)
    result["requests"] = pd.to_numeric(result["requests"], errors="raise").astype(int)
    result["borough"] = result["borough"].fillna("").astype(str).str.strip().str.upper()
    result["borough"] = result["borough"].replace(BOROUGH_NORMALIZATION)
    max_date = result["day"].max().strftime("%Y-%m-%d")
    return result.sort_values(["day", "hour", "borough"]).reset_index(drop=True), max_date
