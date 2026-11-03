"""Selic target and effective daily rates with explicit percentage units."""

import pandas as pd

from .sgs import DateLike, SGSClient

SELIC_TARGET_SERIES_ID = 432
SELIC_EFFECTIVE_DAILY_SERIES_ID = 11


class SelicClient:
    """Fetch official Selic rates without mixing annual and daily percentages."""

    def __init__(self, sgs_client: SGSClient | None = None) -> None:
        self.sgs_client = sgs_client if sgs_client is not None else SGSClient()

    def fetch_target(
        self, start_date: DateLike, end_date: DateLike, *, refresh: bool = False
    ) -> pd.DataFrame:
        """Return the Copom target (SGS 432), expressed in percent per year."""
        result = self.sgs_client.fetch_series(
            SELIC_TARGET_SERIES_ID, start_date, end_date, refresh=refresh
        ).rename(columns={"value": "selic_target_annual_pct"})
        result.attrs["unit"] = "percent_per_year"
        return result

    def fetch_effective_daily(
        self, start_date: DateLike, end_date: DateLike, *, refresh: bool = False
    ) -> pd.DataFrame:
        """Return the effective overnight rate (SGS 11), in percent per day."""
        result = self.sgs_client.fetch_series(
            SELIC_EFFECTIVE_DAILY_SERIES_ID, start_date, end_date, refresh=refresh
        ).rename(columns={"value": "selic_effective_daily_pct"})
        result.attrs["unit"] = "percent_per_day"
        return result

    def fetch(
        self, start_date: DateLike, end_date: DateLike, *, refresh: bool = False
    ) -> pd.DataFrame:
        """Return both series by date without filling non-business-day gaps."""
        target = self.fetch_target(start_date, end_date, refresh=refresh)
        effective = self.fetch_effective_daily(start_date, end_date, refresh=refresh)
        result = target.merge(effective, on="date", how="outer", validate="one_to_one")
        result = result.sort_values("date", ignore_index=True)
        result.attrs = {
            "series_ids": {"selic_target_annual_pct": "432", "selic_effective_daily_pct": "11"},
            "units": {
                "selic_target_annual_pct": "percent_per_year",
                "selic_effective_daily_pct": "percent_per_day",
            },
        }
        return result
