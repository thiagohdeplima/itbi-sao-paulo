"""Download and cache the city's annual ITBI workbooks."""

from collections.abc import Iterable
from pathlib import Path
from tempfile import NamedTemporaryFile

import pandas as pd
import requests
from tqdm.auto import tqdm

WORKBOOK_URLS = {
    2019: "https://www.prefeitura.sp.gov.br/cidade/secretarias/upload/fazenda/arquivos/itbi/ITBI_Setembro_2022/GUIAS_DE_ITBI_PAGAS_(2019).xlsx",
    2020: "https://www.prefeitura.sp.gov.br/cidade/secretarias/upload/fazenda/arquivos/itbi/ITBI_Setembro_2022/GUIAS_DE_ITBI_PAGAS_(2020).xlsx",
    2021: "https://www.prefeitura.sp.gov.br/cidade/secretarias/upload/fazenda/arquivos/itbi/ITBI_Setembro_2022/GUIAS_DE_ITBI_PAGAS_(2021).xlsx",
    2022: "https://www.prefeitura.sp.gov.br/cidade/secretarias/upload/fazenda/arquivos/XLSX/GUIAS_DE_ITBI_PAGAS_12-2022.xlsx",
    2023: "https://www.prefeitura.sp.gov.br/cidade/secretarias/upload/fazenda/arquivos/XLSX/GUIAS-DE-ITBI-PAGAS-2023.xlsx",
    2024: "https://prefeitura.sp.gov.br/cidade/secretarias/upload/fazenda/arquivos/itbi/GUIAS-DE-ITBI-PAGAS-2024.xlsx",
    2025: "https://prefeitura.sp.gov.br/cidade/secretarias/upload/fazenda/arquivos/itbi/GUIAS%20DE%20ITBI%20PAGAS%20%2828012026%29%20XLS.xlsx",
    2026: "https://prefeitura.sp.gov.br/cidade/secretarias/upload/fazenda/arquivos/itbi/GUIAS%20DE%20ITBI%20PAGAS%20%2830092026%29.xlsx",
}
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/156.0.0.0 Safari/537.36"
)


def get_workbook_url(year: int) -> str:
    """Resolve the source URL for a supported year."""
    if 2006 <= year < 2019:
        return (
            "https://www.prefeitura.sp.gov.br/cidade/secretarias/upload/"
            f"fazenda/arquivos/itbi/guias_de_itbi_pagas_{year}.xlsx"
        )
    try:
        return WORKBOOK_URLS[year]
    except KeyError:
        raise ValueError(f"No workbook URL configured for {year}.") from None


def download_workbook(year: int, data_dir: str | Path = "_data") -> Path:
    """Reuse a cached workbook or download it without leaving partial files."""
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    destination = data_dir / f"{year}.xlsx"
    if destination.exists():
        return destination

    url = get_workbook_url(year)
    temporary_path = None
    try:
        with requests.get(
            url, stream=True, headers={"User-Agent": USER_AGENT}, timeout=(10, 120)
        ) as response:
            response.raise_for_status()
            with NamedTemporaryFile(
                dir=data_dir, prefix=f".{year}.", suffix=".part", delete=False
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        temporary_file.write(chunk)
        temporary_path.replace(destination)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return destination


def download_workbooks(
    years: Iterable[int] = range(2006, 2027),
    data_dir: str | Path = "_data",
    *,
    show_progress: bool = True,
) -> pd.DataFrame:
    """Download available years and report failures instead of hiding them."""
    records = []
    for year in tqdm(years, desc="Downloading workbooks", disable=not show_progress):
        path = Path(data_dir) / f"{year}.xlsx"
        cached = path.exists()
        try:
            download_workbook(year, data_dir)
        except (requests.RequestException, OSError) as error:
            records.append({
                "year": year,
                "file": str(path),
                "status": "error",
                "error": str(error),
            })
        else:
            records.append({
                "year": year,
                "file": str(path),
                "status": "cached" if cached else "downloaded",
                "error": None,
            })
    return pd.DataFrame(records, columns=["year", "file", "status", "error"])
