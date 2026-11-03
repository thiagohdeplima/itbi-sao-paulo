"""Fetch and cache dated observations from the BCB SGS JSON API."""

import json
from datetime import date, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import pandas as pd
import requests

DateLike = str | date | datetime
BASE_URL = "https://api.bcb.gov.br/dados/serie"


def validate_series_id(series_id: int) -> None:
    """Require an explicit positive SGS identifier."""
    if isinstance(series_id, bool) or not isinstance(series_id, int) or series_id < 1:
        raise ValueError("series_id must be a positive integer.")


def parse_date(value: DateLike) -> pd.Timestamp:
    """Accept ISO date strings or date objects without a time zone."""
    if isinstance(value, str):
        value = date.fromisoformat(value)
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp) or timestamp.tzinfo is not None:
        raise ValueError("Dates must be valid and must not include a time zone.")
    return timestamp.normalize()


class SGSClient:
    """Download SGS series with explicit dates and optional persistent caching.

    Requests are split into windows shorter than ten years, as required for
    daily SGS series. Cached windows are reused until refresh=True is supplied.
    """

    def __init__(
        self, cache_dir: str | Path | None = "_data/bacen", *, timeout: float = 30
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be greater than zero.")
        self.cache_dir = Path(cache_dir) if cache_dir is not None else None
        self.timeout = timeout

    def fetch_series(
        self,
        series_id: int,
        start_date: DateLike,
        end_date: DateLike,
        *,
        refresh: bool = False,
    ) -> pd.DataFrame:
        """Return sorted date/value observations, preserving missing values."""
        validate_series_id(series_id)
        start = parse_date(start_date)
        end = parse_date(end_date)
        if start > end:
            raise ValueError("start_date must not be after end_date.")

        frames = []
        window_start = start
        while window_start <= end:
            window_end = min(
                window_start + pd.DateOffset(years=10) - pd.Timedelta(days=1), end
            )
            frames.append(self._fetch_window(series_id, window_start, window_end, refresh))
            window_start = window_end + pd.Timedelta(days=1)

        result = pd.concat(frames, ignore_index=True).sort_values("date", ignore_index=True)
        if result["date"].duplicated().any():
            raise ValueError(f"SGS series {series_id} returned duplicate observation dates.")
        result.attrs = {
            "series_id": str(series_id),
            "source_url": f"{BASE_URL}/bcdata.sgs.{series_id}/dados",
        }
        return result

    def _fetch_window(
        self, series_id: int, start: pd.Timestamp, end: pd.Timestamp, refresh: bool
    ) -> pd.DataFrame:
        cache_path = (
            self.cache_dir / f"sgs_{series_id}_{start:%Y%m%d}_{end:%Y%m%d}.json"
            if self.cache_dir is not None else None
        )
        if cache_path is not None and cache_path.exists() and not refresh:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        else:
            payload = self._request_window(series_id, start, end)
            frame = self._parse_payload(payload)
            # Invalid responses must never become successful cache entries.
            if cache_path is not None:
                self._write_cache(cache_path, payload)
            return frame.loc[frame["date"].between(start, end)].reset_index(drop=True)
        frame = self._parse_payload(payload)
        return frame.loc[frame["date"].between(start, end)].reset_index(drop=True)

    def _request_window(
        self, series_id: int, start: pd.Timestamp, end: pd.Timestamp
    ) -> list[dict[str, Any]]:
        with requests.get(
            f"{BASE_URL}/bcdata.sgs.{series_id}/dados",
            params={
                "formato": "json",
                "dataInicial": start.strftime("%d/%m/%Y"),
                "dataFinal": end.strftime("%d/%m/%Y"),
            },
            timeout=self.timeout,
        ) as response:
            if response.status_code == 404:
                try:
                    payload = response.json()
                except ValueError:
                    response.raise_for_status()
                    raise
                error = payload.get("erro") if isinstance(payload, dict) else None
                # SGS uses this specific error for intervals without observations.
                if isinstance(error, dict) and str(error.get("detail", "")).endswith(
                    ": Value(s) not found"
                ):
                    return []
            response.raise_for_status()
            return response.json()

    @staticmethod
    def _parse_payload(payload: object) -> pd.DataFrame:
        if not isinstance(payload, list) or any(
            not isinstance(row, dict) or not {"data", "valor"} <= row.keys()
            for row in payload
        ):
            raise ValueError("Unexpected SGS response: expected dated value records.")
        frame = pd.DataFrame(payload, columns=["data", "valor"])
        dates = pd.to_datetime(frame["data"], format="%d/%m/%Y", errors="raise")
        if dates.isna().any() or dates.duplicated().any():
            raise ValueError("SGS observation dates must be present and unique.")
        values = frame["valor"].astype("string").str.replace(",", ".", regex=False)
        values = pd.to_numeric(values.replace("", pd.NA), errors="raise").astype("Float64")
        if values.isin([float("inf"), float("-inf")]).any():
            raise ValueError("SGS observations must be finite numbers or missing values.")
        return pd.DataFrame({"date": dates.astype("datetime64[ns]"), "value": values})

    @staticmethod
    def _write_cache(path: Path, payload: list[dict[str, Any]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = None
        try:
            with NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent,
                prefix=f".{path.stem}.", suffix=".part", delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                json.dump(payload, temporary_file, ensure_ascii=False)
            temporary_path.replace(path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
