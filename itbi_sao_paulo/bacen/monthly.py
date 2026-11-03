"""Load economic observations once and enrich transactions by calendar month."""

import pandas as pd
from pathlib import Path
from tempfile import NamedTemporaryFile

from .financing import RealEstateFinancingClient
from .selic import SelicClient
from .sgs import SGSClient

MONTHLY_INDICATOR_COLUMNS = (
    "transaction_month",
    "selic_target_annual_pct_monthly_mean",
    "selic_effective_daily_pct_monthly_mean",
    "real_estate_financing_brl_millions",
)


def transaction_months(data: pd.DataFrame) -> pd.Series:
    """Extract calendar months while preserving rows with invalid source dates."""
    return pd.to_datetime(data["transaction_date"], format="mixed", errors="coerce").dt.to_period("M")


class MonthlyEconomicClient:
    """Fetch each source over the transaction period, then aggregate in memory."""

    def __init__(self, sgs_client: SGSClient | None = None) -> None:
        self.sgs_client = sgs_client if sgs_client is not None else SGSClient()

    def fetch_for_transactions(
        self, data: pd.DataFrame, *, refresh: bool = False
    ) -> pd.DataFrame:
        """Return one row per month, including months without published data.

        Selic columns are arithmetic means of published daily observations.
        The effective daily mean is not a compounded monthly interest rate.
        """
        months = transaction_months(data).dropna()
        if months.empty:
            raise ValueError("No valid transaction dates available for economic data lookup.")
        # SGS 11, the earliest supported source, begins in June 1986.
        # Source placeholders such as year 0001 must not expand API requests.
        first_month = max(months.min(), pd.Period("1986-06", freq="M"))
        start = first_month.start_time
        end = min(months.max().end_time.normalize(), pd.Timestamp.today().normalize())
        if start > end:
            raise ValueError("All transaction dates are in future months.")
        rates = SelicClient(self.sgs_client).fetch(start, end, refresh=refresh)
        rates["transaction_month"] = rates["date"].dt.to_period("M")
        monthly_rates = rates.groupby("transaction_month")[[
            "selic_target_annual_pct", "selic_effective_daily_pct"
        ]].mean().rename(columns={
            "selic_target_annual_pct": "selic_target_annual_pct_monthly_mean",
            "selic_effective_daily_pct": "selic_effective_daily_pct_monthly_mean",
        })
        financing = RealEstateFinancingClient(self.sgs_client).fetch(start, end, refresh=refresh)
        financing["transaction_month"] = financing["date"].dt.to_period("M")
        if financing["transaction_month"].duplicated().any():
            raise ValueError("Multiple financing observations found for the same month.")
        financing = financing.set_index("transaction_month")[["real_estate_financing_brl_millions"]]
        calendar = pd.DataFrame(index=pd.period_range(
            first_month, months.max(), freq="M", name="transaction_month"
        ))
        return calendar.join(monthly_rates).join(financing).reset_index()


def enrich_transactions(data: pd.DataFrame, monthly_indicators: pd.DataFrame) -> pd.DataFrame:
    """Match monthly indicators without network calls, row expansion, or reordering."""
    if monthly_indicators["transaction_month"].isna().any():
        raise ValueError("Indicator months must not be missing.")
    lookup = monthly_indicators.set_index("transaction_month")
    if not lookup.index.is_unique:
        raise ValueError("Monthly indicators must have exactly one row per month.")
    if not isinstance(lookup.index, pd.PeriodIndex) or lookup.index.freqstr != "M":
        raise ValueError("transaction_month must use monthly pandas Period values.")
    result = data.assign(transaction_month=transaction_months(data))
    for column in lookup.columns:
        result[column] = result["transaction_month"].map(lookup[column])
    return result


def load_or_fetch_monthly_indicators(
    data: pd.DataFrame,
    cache_path: str | Path = "_data/cache/monthly_economic_indicators.csv",
    *,
    client: MonthlyEconomicClient | None = None,
    refresh: bool = False,
) -> pd.DataFrame:
    """Reuse the monthly CSV cache or fetch and save observations when absent."""
    cache_path = Path(cache_path)
    if cache_path.exists() and not refresh:
        indicators = pd.read_csv(cache_path, dtype={"transaction_month": "string"})
        if tuple(indicators.columns) != MONTHLY_INDICATOR_COLUMNS:
            raise ValueError(f"Unexpected monthly indicator columns in {cache_path}.")
        indicators["transaction_month"] = pd.PeriodIndex(
            indicators["transaction_month"], freq="M"
        )
        return indicators

    active_client = client if client is not None else MonthlyEconomicClient()
    indicators = active_client.fetch_for_transactions(data, refresh=refresh)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="", dir=cache_path.parent,
            prefix=f".{cache_path.stem}.", suffix=".part", delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            indicators.to_csv(temporary_file, index=False)
        temporary_path.replace(cache_path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return indicators
