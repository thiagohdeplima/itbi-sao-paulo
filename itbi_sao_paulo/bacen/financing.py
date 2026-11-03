"""Fetch application counts only when their SGS sources are explicitly known."""

import pandas as pd

from .sgs import DateLike, SGSClient, validate_series_id


class RealEstateFinancingClient:
    """Fetch monthly earmarked real estate lending to households (SGS 20704)."""

    SERIES_ID = 20704

    def __init__(self, sgs_client: SGSClient | None = None) -> None:
        self.sgs_client = sgs_client if sgs_client is not None else SGSClient()

    def fetch(
        self, start_date: DateLike, end_date: DateLike, *, refresh: bool = False
    ) -> pd.DataFrame:
        """Return new lending amounts in BRL millions, retaining monthly dates."""
        result = self.sgs_client.fetch_series(
            self.SERIES_ID, start_date, end_date, refresh=refresh
        ).rename(columns={"value": "real_estate_financing_brl_millions"})
        result.attrs.update(unit="BRL_millions", frequency="monthly")
        return result


class FinancingClient:
    """Download requested and denied financing counts from confirmed SGS IDs.

    No official default series are assumed: public credit disbursements,
    outstanding loans, and survey indices do not measure application counts.
    The caller must verify that both series describe counts with matching
    scope, geography, frequency, and reference-period definitions.
    """

    def __init__(
        self,
        requested_series_id: int,
        denied_series_id: int,
        *,
        sgs_client: SGSClient | None = None,
    ) -> None:
        validate_series_id(requested_series_id)
        validate_series_id(denied_series_id)
        if requested_series_id == denied_series_id:
            raise ValueError("Requested and denied counts must use different SGS series.")
        self.requested_series_id = requested_series_id
        self.denied_series_id = denied_series_id
        self.sgs_client = sgs_client if sgs_client is not None else SGSClient()

    def fetch(
        self, start_date: DateLike, end_date: DateLike, *, refresh: bool = False
    ) -> pd.DataFrame:
        """Return nullable integer counts; missing observations remain missing."""
        frames = []
        for series_id, column in (
            (self.requested_series_id, "financing_requested_count"),
            (self.denied_series_id, "financing_denied_count"),
        ):
            frame = self.sgs_client.fetch_series(
                series_id, start_date, end_date, refresh=refresh
            ).rename(columns={"value": column})
            values = frame[column]
            if ((values < 0) | (values % 1 != 0)).any():
                raise ValueError(f"SGS series {series_id} must contain nonnegative integer counts.")
            frame[column] = values.astype("Int64")
            frames.append(frame)
        result = frames[0].merge(frames[1], on="date", how="outer", validate="one_to_one")
        result = result.sort_values("date", ignore_index=True)
        result.attrs = {
            "series_ids": {
                "financing_requested_count": str(self.requested_series_id),
                "financing_denied_count": str(self.denied_series_id),
            },
            "unit": "application_count",
        }
        return result
