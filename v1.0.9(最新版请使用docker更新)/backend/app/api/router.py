from fastapi import APIRouter

from app.api.routes import audit_logs, auth, cache_management, dashboard, drive_accounts, health, magic_regex, media_discovery, metrics, notifications, openlist_settings, permissions, plugins, resource_search, roles, setup, sync_plugins, sync_tasks, tasks, tmdb_cache, tmdb_settings, users


api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(setup.router, prefix="/setup", tags=["setup"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(roles.router, prefix="/roles", tags=["roles"])
api_router.include_router(permissions.router, prefix="/permissions", tags=["permissions"])
api_router.include_router(audit_logs.router, prefix="/audit-logs", tags=["audit-logs"])
api_router.include_router(drive_accounts.router, prefix="/drive-accounts", tags=["drive-accounts"])
api_router.include_router(plugins.router, prefix="/plugins", tags=["plugins"])
api_router.include_router(sync_plugins.router, prefix="/sync-plugins", tags=["sync-plugins"])
api_router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
api_router.include_router(sync_tasks.router, prefix="/sync-tasks", tags=["sync-tasks"])
api_router.include_router(magic_regex.router, prefix="/magic-regex", tags=["magic-regex"])
api_router.include_router(resource_search.router, prefix="/resource-search", tags=["resource-search"])
api_router.include_router(notifications.router, prefix="/notifications", tags=["notifications"])
api_router.include_router(cache_management.router, prefix="/cache", tags=["cache"])
api_router.include_router(openlist_settings.router, prefix="/openlist", tags=["openlist"])
api_router.include_router(tmdb_settings.router, prefix="/tmdb", tags=["tmdb"])
api_router.include_router(tmdb_cache.router, prefix="/tmdb", tags=["tmdb"])
api_router.include_router(media_discovery.router, prefix="/media", tags=["media"])
api_router.include_router(health.router, tags=["health"])
api_router.include_router(metrics.router, tags=["metrics"])
