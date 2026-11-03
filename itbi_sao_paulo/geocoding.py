"""Deduplicate addresses and geocode them with a local Nominatim service."""

import os
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple
from urllib.parse import urlsplit

import pandas as pd
import pygeohash as pgh
from geopy.exc import GeocoderServiceError
from geopy.extra.rate_limiter import RateLimiter
from geopy.geocoders import Nominatim
from tqdm.auto import tqdm

from .geocoding_cache import GeocodingCache

ADDRESS_COLUMNS = ("street_name", "street_number", "neighborhood", "postal_code")
RESULT_COLUMNS = ("latitude", "longitude", "geocoding_status", "geocoding_error")


@dataclass(frozen=True)
class GeocodingConfig:
    """Connection and concurrency settings for a local Nominatim instance."""

    api_url: str = field(
        default_factory=lambda: os.environ.get("NOMINATIM_API_URL", "http://127.0.0.1:8080")
    )
    max_workers: int = 8
    geohash_precision: int = 5
    timeout: float = 30
    cache_path: str | Path | None = "_data/geocoding.sqlite3"
    cache_batch_size: int = 100

    def __post_init__(self) -> None:
        api = urlsplit(self.api_url)
        if api.scheme not in {"http", "https"} or not api.netloc:
            raise ValueError("api_url must be a valid HTTP URL.")
        if self.max_workers < 1:
            raise ValueError("max_workers must be at least 1.")
        if not 1 <= self.geohash_precision <= 12:
            raise ValueError("geohash_precision must be between 1 and 12.")
        if self.timeout <= 0:
            raise ValueError("timeout must be greater than zero.")
        if self.cache_batch_size < 1:
            raise ValueError("cache_batch_size must be at least 1.")


class GeocodingResult(NamedTuple):
    latitude: float | None
    longitude: float | None
    status: str
    error: str | None


def normalize_address_text(value: object) -> str:
    """Collapse whitespace and treat missing address components as empty."""
    return "" if pd.isna(value) else " ".join(str(value).strip().split())


def build_address(
    street_name: object,
    street_number: object,
    neighborhood: object,
    postal_code: object,
) -> str | None:
    """Build a building-level address without apartment complements."""
    street = normalize_address_text(street_name)
    if not street:
        return None
    number = normalize_address_text(street_number).removesuffix(".0")
    if number in {"0", "S/N", "SN"}:
        number = ""
    district = normalize_address_text(neighborhood)
    code = normalize_address_text(postal_code).removesuffix(".0").replace("-", "")
    code = code.zfill(8) if code.isdigit() and len(code) <= 8 else ""
    if code == "00000000":
        code = ""
    return ", ".join(
        part for part in (street, number, district, code, "São Paulo, SP, Brasil") if part
    ).upper()


class GeocodingClient:
    """Reuse persistent results and process a bounded queue in completion order."""

    def __init__(self, config: GeocodingConfig | None = None) -> None:
        self.config = config if config is not None else GeocodingConfig()
        self.cache: dict[tuple[str, str], GeocodingResult] = {}
        self._clients = threading.local()

    def _process_pending(
        self,
        pending: list,
        api_url: str,
        store,
        show_progress: bool,
        *,
        total: int,
        completed: int,
    ) -> None:
        buffered = {}
        remaining = iter(pending)
        executor = ThreadPoolExecutor(max_workers=self.config.max_workers)
        active = {}

        def submit_next() -> None:
            address = next(remaining, None)
            if address is not None:
                active[executor.submit(self._lookup, address)] = address

        try:
            for _ in range(min(len(pending), self.config.max_workers * 2)):
                submit_next()
            with tqdm(
                total=total,
                initial=completed,
                desc="Geocoding unique addresses",
                disable=not show_progress,
            ) as progress:
                while active:
                    completed, _ = wait(active, return_when=FIRST_COMPLETED)
                    for future in completed:
                        address = active.pop(future)
                        lookup = future.result()
                        self.cache[(api_url, address)] = lookup
                        buffered[address] = lookup
                        if len(buffered) >= self.config.cache_batch_size:
                            if store is not None:
                                store.save(api_url, buffered)
                            buffered.clear()
                        progress.update(1)
                        submit_next()
        finally:
            # Flush collected results on normal exit, exceptions, and Ctrl-C.
            try:
                if store is not None:
                    store.save(api_url, buffered)
            finally:
                executor.shutdown(wait=True, cancel_futures=True)

    def _lookup(self, address: str) -> GeocodingResult:
        if not hasattr(self._clients, "search"):
            api = urlsplit(self.config.api_url.rstrip("/"))
            geocoder = Nominatim(
                domain=api.netloc,
                scheme=api.scheme,
                user_agent="itbi-sao-paulo",
                timeout=self.config.timeout,
                proxies={},
            )
            self._clients.search = RateLimiter(
                geocoder.geocode,
                min_delay_seconds=0,
                max_retries=2,
                error_wait_seconds=0.5,
                swallow_exceptions=False,
            )
        try:
            location = self._clients.search(address, country_codes="br", exactly_one=True)
            if location is None:
                return GeocodingResult(None, None, "not_found", None)
            return GeocodingResult(location.latitude, location.longitude, "found", None)
        except GeocoderServiceError as error:
            return GeocodingResult(None, None, "error", str(error))

    def geocode(
        self, data: pd.DataFrame, *, show_progress: bool = True
    ) -> pd.DataFrame:
        """Return an enriched table; cache misses are queried once per address."""
        missing_columns = set(ADDRESS_COLUMNS) - set(data.columns)
        if missing_columns:
            raise ValueError(f"Missing address columns: {', '.join(sorted(missing_columns))}.")
        result = data.assign(
            geocoding_address=pd.Series(
                [
                    build_address(*values)
                    for values in data.loc[:, ADDRESS_COLUMNS].itertuples(index=False, name=None)
                ],
                index=data.index,
                dtype="string",
            )
        )
        addresses = result["geocoding_address"].dropna().unique()
        api_url = self.config.api_url.rstrip("/")
        store = (
            GeocodingCache(self.config.cache_path)
            if self.config.cache_path is not None else None
        )
        if store is not None:
            for address, saved in store.load(api_url).items():
                self.cache.setdefault((api_url, address), GeocodingResult(*saved))
        pending = [
            address for address in addresses
            if (api_url, address) not in self.cache
            or self.cache[(api_url, address)].status == "error"
        ]
        cached_count = len(addresses) - len(pending)
        self._process_pending(
            pending,
            api_url,
            store,
            show_progress,
            total=len(addresses),
            completed=cached_count,
        )

        locations = pd.DataFrame(
            [self.cache[(api_url, address)] for address in addresses],
            index=addresses,
            columns=RESULT_COLUMNS,
        )
        locations = locations.astype({"latitude": "float64", "longitude": "float64"})
        locations["geohash"] = [
            pgh.encode(
                latitude=latitude,
                longitude=longitude,
                precision=self.config.geohash_precision,
            )
            if pd.notna(latitude) and pd.notna(longitude) else None
            for latitude, longitude in locations[["latitude", "longitude"]].itertuples(
                index=False, name=None
            )
        ]
        for column in locations.columns:
            result[column] = result["geocoding_address"].map(locations[column])
            if column in {"geocoding_status", "geocoding_error", "geohash"}:
                result[column] = result[column].astype("string")
        result["geocoding_status"] = result["geocoding_status"].fillna("incomplete_address")
        return result
