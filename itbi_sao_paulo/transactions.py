"""Select transactions for exploration and export."""

import pandas as pd

from .schema import PURCHASE_TRANSACTION


def select_transactions(
    data: pd.DataFrame, *, geocoded_only: bool = False, purchases_only: bool = False
) -> pd.DataFrame:
    """Apply the notebook's optional location and purchase filters."""
    mask = pd.Series(True, index=data.index)
    if geocoded_only:
        mask &= data["geocoding_status"].eq("found")
    if purchases_only:
        mask &= data["transaction_nature"].eq(PURCHASE_TRANSACTION)
    return data.loc[mask]
