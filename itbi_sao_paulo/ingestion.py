"""Read monthly worksheets into a uniform transaction table."""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from tqdm.auto import tqdm

from .schema import COLUMNS, MONTHLY_SHEET_PATTERN, SOURCE_COLUMNS, normalize_columns


@dataclass
class TransactionImport:
    """Imported transactions and source audit tables."""

    data: pd.DataFrame
    summary: pd.DataFrame
    extra_values: pd.DataFrame


def read_monthly_sheet(
    workbook: pd.ExcelFile, sheet_name: str
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Handle missing headers and retain values beyond the official columns."""
    first_row = pd.read_excel(workbook, sheet_name=sheet_name, header=None, nrows=1)
    # JAN-2024 and OUT-2024 start with a transaction rather than a header.
    has_header = (
        not first_row.empty
        and str(first_row.iat[0, 0]).strip() == SOURCE_COLUMNS[0]
    )
    frame = pd.read_excel(
        workbook,
        sheet_name=sheet_name,
        header=None,
        skiprows=int(has_header),
        dtype=object,
    ).dropna(how="all")
    extra_values = [
        {
            "sheet": sheet_name,
            "excel_row": int(row) + 1 + int(has_header),
            "excel_column": int(column) + 1,
            "value": value,
        }
        for column in frame.columns[len(COLUMNS):]
        for row, value in frame[column].dropna().items()
    ]
    return normalize_columns(frame), extra_values


def load_transactions(
    data_dir: str | Path = "_data", *, show_progress: bool = True
) -> TransactionImport:
    """Load annual workbooks, excluding legends and other auxiliary sheets."""
    data_dir = Path(data_dir)
    workbooks = sorted(data_dir.glob("[0-9][0-9][0-9][0-9].xlsx"))
    if not workbooks:
        raise FileNotFoundError(f"No annual workbooks found in {data_dir}.")

    frames = []
    summary = []
    extra_values = []
    for path in tqdm(
        workbooks,
        desc="Reading workbooks",
        disable=not show_progress,
        position=0,
    ):
        with pd.ExcelFile(path) as workbook:
            for sheet_name in tqdm(
                workbook.sheet_names,
                desc=f"Worksheets in {path.name}",
                disable=not show_progress,
                position=1,
                leave=False,
            ):
                if not re.fullmatch(MONTHLY_SHEET_PATTERN, sheet_name):
                    continue
                frame, sheet_extra_values = read_monthly_sheet(workbook, sheet_name)
                frames.append(frame)
                summary.append({"file": str(path), "sheet": sheet_name, "records": len(frame)})
                extra_values.extend(
                    {"file": str(path), **item} for item in sheet_extra_values
                )
    if not frames:
        raise ValueError("No monthly worksheets found in the annual workbooks.")

    return TransactionImport(
        data=pd.concat(frames, ignore_index=True),
        summary=pd.DataFrame(summary, columns=["file", "sheet", "records"]),
        extra_values=pd.DataFrame(
            extra_values, columns=["file", "sheet", "excel_row", "excel_column", "value"]
        ),
    )
