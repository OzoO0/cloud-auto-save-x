from __future__ import annotations

import logging
from typing import Any, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


logger = logging.getLogger(__name__)


class TMDBClient:
    def __init__(self, api_key: str | None = None, *, language: str = "zh-CN"):
        self.api_key = api_key
        self.primary_url = "https://api.tmdb.org/3"
        self.backup_url = "https://api.themoviedb.org/3"
        self.current_url = self.primary_url
        self.language = language

        self.session = requests.Session()
        retries = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        adapter = HTTPAdapter(max_retries=retries, pool_connections=20, pool_maxsize=50)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        self._cache: dict[Any, Any] = {}
        self._cache_ttl_seconds = 600

    def is_configured(self) -> bool:
        return bool(self.api_key and str(self.api_key).strip())

    def _make_request(self, endpoint: str, params: dict[str, Any] | None = None) -> Optional[dict[str, Any]]:
        if not self.is_configured():
            return None

        if params is None:
            params = {}

        params.update({"api_key": self.api_key, "language": self.language, "include_adult": False})

        try:
            from time import time as _now

            cache_key = (endpoint, tuple(sorted((params or {}).items())))
            cached = self._cache.get(cache_key)
            if cached and (_now() - cached[0]) < self._cache_ttl_seconds:
                return cached[1]
        except Exception:
            cache_key = None

        try:
            url = f"{self.current_url}{endpoint}"
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            try:
                if cache_key is not None:
                    self._cache[cache_key] = (_now(), data)
            except Exception:
                pass
            return data
        except Exception as e:
            logger.debug(f"TMDB主地址请求失败: {e}")
            if self.current_url == self.primary_url:
                self.current_url = self.backup_url
                try:
                    url = f"{self.current_url}{endpoint}"
                    response = self.session.get(url, params=params, timeout=10)
                    response.raise_for_status()
                    data = response.json()
                    try:
                        if cache_key is not None:
                            self._cache[cache_key] = (_now(), data)
                    except Exception:
                        pass
                    return data
                except Exception as backup_e:
                    logger.error(f"TMDB备用地址请求也失败: {backup_e}")
                    self.current_url = self.primary_url
                    return None
            self.current_url = self.primary_url
            return None

    def search_tv_all(self, query: str, year: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"query": query}
        if year:
            params["first_air_date_year"] = year
        result = self._make_request("/search/tv", params)
        if result and result.get("results"):
            return list(result["results"])
        return []

    def search_movie_all(self, query: str, year: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"query": query}
        if year:
            params["year"] = year
        result = self._make_request("/search/movie", params)
        if result and result.get("results"):
            return list(result["results"])
        return []

    def search_multi(self, query: str) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"query": query}
        result = self._make_request("/search/multi", params)
        if result and result.get("results"):
            return list(result["results"])
        return []

    def search_tv_page(self, query: str, *, year: str | None = None, page: int = 1) -> dict[str, Any]:
        params: dict[str, Any] = {"query": query, "page": page}
        if year:
            params["first_air_date_year"] = year
        return self._make_request("/search/tv", params) or {}

    def search_movie_page(self, query: str, *, year: str | None = None, page: int = 1) -> dict[str, Any]:
        params: dict[str, Any] = {"query": query, "page": page}
        if year:
            params["year"] = year
        return self._make_request("/search/movie", params) or {}

    def search_multi_page(self, query: str, *, page: int = 1) -> dict[str, Any]:
        params: dict[str, Any] = {"query": query, "page": page}
        return self._make_request("/search/multi", params) or {}

    def get_tv_details(self, tv_id: int, *, language: str | None = None) -> Optional[dict[str, Any]]:
        if language:
            return self._make_request(f"/tv/{tv_id}", {"language": language})
        return self._make_request(f"/tv/{tv_id}")

    def get_tv_season(self, tv_id: int, season_number: int, *, language: str | None = None) -> Optional[dict[str, Any]]:
        if language:
            return self._make_request(f"/tv/{tv_id}/season/{season_number}", {"language": language})
        return self._make_request(f"/tv/{tv_id}/season/{season_number}")

    def get_movie_details(self, movie_id: int, *, language: str | None = None) -> Optional[dict[str, Any]]:
        if language:
            return self._make_request(f"/movie/{movie_id}", {"language": language})
        return self._make_request(f"/movie/{movie_id}")
