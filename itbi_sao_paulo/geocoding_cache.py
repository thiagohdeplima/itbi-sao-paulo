"""Transactional storage for reusable Nominatim results."""

import sqlite3
from contextlib import closing
from pathlib import Path


class GeocodingCache:
    """Store coordinates by endpoint and normalized address, independently of geohash."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=30)) as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS geocoding_cache_v1 (
                    api_url TEXT NOT NULL,
                    address TEXT NOT NULL,
                    latitude REAL,
                    longitude REAL,
                    status TEXT NOT NULL,
                    error TEXT,
                    PRIMARY KEY (api_url, address)
                )
            """)
            connection.commit()

    def load(self, api_url: str) -> dict:
        with closing(sqlite3.connect(self.path, timeout=30)) as connection:
            rows = connection.execute(
                "SELECT address, latitude, longitude, status, error "
                "FROM geocoding_cache_v1 WHERE api_url = ?", (api_url,)
            )
            return {address: (latitude, longitude, status, error)
                    for address, latitude, longitude, status, error in rows}

    def save(self, api_url: str, results: dict) -> None:
        if not results:
            return
        with closing(sqlite3.connect(self.path, timeout=30)) as connection:
            with connection:
                connection.executemany(
                    "INSERT OR REPLACE INTO geocoding_cache_v1 "
                    "(api_url, address, latitude, longitude, status, error) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    ((api_url, address, *result) for address, result in results.items()),
                )
