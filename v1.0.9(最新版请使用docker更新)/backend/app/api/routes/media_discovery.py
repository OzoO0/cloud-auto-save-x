from __future__ import annotations

from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session
import requests

from app.core.deps import require_permissions
from app.core.permissions import TASK_READ
from app.core.settings import settings
from app.db.session import get_db
from app.schemas.media_discovery import DoubanCategoryListOut, MediaDiscoverListOut, TMDBDetailOut, TMDBSearchListOut
from app.services.media_discovery import fetch_douban_list, list_douban_categories, tmdb_detail, tmdb_search
from app.services.proxy_image_cache import ProxyImageCacheConfig, fetch_store_and_build_response, resolve_proxy_image_cache_dir, try_build_cached_response
from app.services.tmdb_settings import get_or_create_tmdb_setting, get_tmdb_runtime_config
from app.thirdparty.douban_client import DoubanClient


router = APIRouter()
_douban = DoubanClient()


@router.get("/douban/categories", response_model=DoubanCategoryListOut, dependencies=[Depends(require_permissions(TASK_READ))])
def get_douban_categories() -> DoubanCategoryListOut:
    return DoubanCategoryListOut(categories=list_douban_categories())


@router.get("/douban/list", response_model=MediaDiscoverListOut, dependencies=[Depends(require_permissions(TASK_READ))])
def get_douban_list(
    main_category: str = Query(..., min_length=1, max_length=64),
    sub_category: str = Query("", max_length=64),
    start: int = Query(0, ge=0, le=5000),
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
) -> MediaDiscoverListOut:
    raw = fetch_douban_list(main_category=main_category, sub_category=sub_category, start=start, limit=limit)
    data = raw.get("data") or {}
    items = list(data.get("items") or [])
    total = int(data.get("total") or len(items))

    setting = get_or_create_tmdb_setting(db)
    cfg = get_tmdb_runtime_config(setting)
    tmdb_configured = bool(str(cfg.get("api_key") or "").strip())

    enriched = [{**x, "tmdb": None} for x in items]
    return MediaDiscoverListOut(
        success=bool(raw.get("success", True)),
        message=raw.get("message"),
        notice=raw.get("notice"),
        tmdb_configured=tmdb_configured,
        is_mock_data=data.get("is_mock_data"),
        mock_reason=data.get("mock_reason"),
        total=total,
        items=enriched,
    )


@router.get("/search", response_model=TMDBSearchListOut, dependencies=[Depends(require_permissions(TASK_READ))])
def get_tmdb_search(
    q: str = Query(..., min_length=1, max_length=128),
    type: str = Query("multi", max_length=16),
    page: int = Query(1, ge=1, le=500),
    year: str | None = Query(default=None, max_length=8),
    db: Session = Depends(get_db),
) -> TMDBSearchListOut:
    configured, items, page_no, total_pages, total_results = tmdb_search(db, q=q, search_type=type, page=page, year=year)
    return TMDBSearchListOut(
        configured=configured,
        page=page_no,
        total_pages=total_pages,
        total_results=total_results,
        items=items,
    )


@router.get("/{media_type}/{tmdb_id}", response_model=TMDBDetailOut, dependencies=[Depends(require_permissions(TASK_READ))])
def get_tmdb_detail(
    media_type: str,
    tmdb_id: int,
    db: Session = Depends(get_db),
) -> TMDBDetailOut:
    mt = str(media_type or "").strip().lower()
    if mt not in ("movie", "tv"):
        return TMDBDetailOut(media_type=mt or media_type, data={}, update_weekdays=[], episode_weekdays=[])
    configured, data, update_weekdays, episode_weekdays = tmdb_detail(db, media_type=mt, tmdb_id=tmdb_id)  # type: ignore[arg-type]
    db.commit()
    return TMDBDetailOut(
        media_type=mt,
        data=data or {},
        update_weekdays=update_weekdays or [],
        episode_weekdays=episode_weekdays or [],
    )


@router.get("/proxy-image")
def get_proxy_image(request: Request, url: str = Query(..., min_length=8, max_length=2048)):
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return Response(status_code=400)
    host = (parsed.hostname or "").lower()
    if not host.endswith("doubanio.com") and not host.endswith("douban.com"):
        return Response(status_code=400)
    
    ua = str(_douban.session.headers.get("User-Agent") or "").strip()
    if not ua:
        ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1"
    headers = {
        "User-Agent": ua,
        "Referer": "https://movie.douban.com/",
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    
    try:
        ttl = max(int(settings.media_proxy_image_cache_ttl_seconds or 0), 1)
        cache_control = f"public, max-age={ttl}"
        cfg = ProxyImageCacheConfig(
            enabled=bool(settings.media_proxy_image_cache_enabled),
            cache_dir=resolve_proxy_image_cache_dir(
                database_url=settings.database_url,
                explicit_dir=settings.media_proxy_image_cache_dir,
            ),
            ttl_seconds=ttl,
            max_file_bytes=int(settings.media_proxy_image_cache_max_file_bytes or 0),
            max_total_bytes=int(settings.media_proxy_image_cache_max_total_bytes or 0),
        )

        cached, _state = try_build_cached_response(
            cfg=cfg,
            url=url,
            if_none_match=request.headers.get("if-none-match"),
            cache_control=cache_control,
        )
        if cached is not None:
            return cached

        res, _state = fetch_store_and_build_response(cfg=cfg, session=_douban.session, url=url, cache_control=cache_control, headers=headers)
        return res
    except requests.RequestException as exc:
        status = 404
        if getattr(exc, "response", None) is not None and getattr(exc.response, "status_code", None) is not None:
            status = int(exc.response.status_code)
        return Response(status_code=status)
