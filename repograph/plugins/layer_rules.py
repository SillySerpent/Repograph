"""Layer and role detection rules for architecture classification (Block G1).

All heuristic patterns are defined here — the classification phase reads these
rules; it does not contain the rules itself.  This keeps p06b_layer_classify.py
clean and the rules extensible without touching phase logic.

Rule evaluation order (highest priority first):
  1. Explicit framework tags (set by p03b_framework_tags — already on the node)
  2. Import-based layer detection
  3. File-path heuristics
  4. Default: "unknown"
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Import-based layer detection
# ---------------------------------------------------------------------------
# If a file's resolved imports include any module in a set, assign that layer.
# Keys are layers; values are sets of module name prefixes (checked with
# ``startswith`` against the resolved module path or raw import module_path).

IMPORT_LAYER_RULES: dict[str, set[str]] = {
    "persistence": {
        "sqlalchemy", "alembic", "psycopg2", "asyncpg", "aiopg",
        "pymongo", "motor", "redis", "aioredis", "aiomysql",
        "django.db", "peewee", "tortoise", "databases", "prisma",
        "pymysql", "cx_Oracle", "pyodbc", "sqlite3",
    },
    "api": {
        "flask", "fastapi", "django.views", "django.http",
        "django.urls", "starlette", "falcon", "tornado",
        "aiohttp.web", "sanic", "quart", "litestar",
        "express", "koa", "hapi", "nestjs",
        "@nestjs",
    },
    "ui": {
        "react", "vue", "svelte", "next/navigation", "next/router",
        "@angular", "preact", "@remix-run", "gatsby",
    },
    "business_logic": {
        # Services that don't fit api/persistence/ui — broad catch for service layer
        "celery", "dramatiq", "rq", "apscheduler",
    },
}

# ---------------------------------------------------------------------------
# File-path layer heuristics
# ---------------------------------------------------------------------------
# Checked against the file's path (lowercased).  The first matching pattern wins.
# Each entry is (path_fragment, layer).

PATH_LAYER_RULES: list[tuple[str, str]] = [
    # Persistence / DB
    ("/models/", "persistence"),
    ("/model/", "persistence"),
    ("/entities/", "persistence"),
    ("/entity/", "persistence"),
    ("/repositories/", "persistence"),
    ("/repository/", "persistence"),
    ("/db/", "persistence"),
    ("/database/", "persistence"),
    ("/migrations/", "persistence"),
    ("/dao/", "persistence"),
    # API layer
    ("/routes/", "api"),
    ("/route/", "api"),
    ("/handlers/", "api"),
    ("/handler/", "api"),
    ("/controllers/", "api"),
    ("/controller/", "api"),
    ("/views/", "api"),
    ("/api/", "api"),
    ("/endpoints/", "api"),
    # UI layer
    ("/pages/", "ui"),
    ("/page/", "ui"),
    ("/components/", "ui"),
    ("/component/", "ui"),
    ("/templates/", "ui"),
    ("/template/", "ui"),
    # Business logic / service layer
    ("/services/", "business_logic"),
    ("/service/", "business_logic"),
    ("/domain/", "business_logic"),
    ("/usecases/", "business_logic"),
    ("/use_cases/", "business_logic"),
    # Utilities
    ("/utils/", "util"),
    ("/util/", "util"),
    ("/helpers/", "util"),
    ("/helper/", "util"),
    ("/lib/", "util"),
    ("/libs/", "util"),
    ("/common/", "util"),
    ("/shared/", "util"),
]

# ---------------------------------------------------------------------------
# File-path role heuristics (for File nodes)
# ---------------------------------------------------------------------------
# Same structure as PATH_LAYER_RULES but maps to roles.

PATH_ROLE_RULES: list[tuple[str, str]] = [
    ("/repositories/", "repository"),
    ("/repository/", "repository"),
    ("/services/", "service"),
    ("/service/", "service"),
    ("/controllers/", "controller"),
    ("/controller/", "controller"),
    ("/routes/", "handler"),
    ("/route/", "handler"),
    ("/views/", "handler"),
    ("/api/", "handler"),
    ("/endpoints/", "handler"),
    ("/handlers/", "handler"),
    ("/handler/", "handler"),
    ("/pages/", "page"),
    ("/page/", "page"),
    ("/components/", "component"),
    ("/component/", "component"),
    ("/utils/", "util"),
    ("/util/", "util"),
    ("/helpers/", "helper"),
    ("/models/", "model"),
    ("/model/", "model"),
    ("/entities/", "model"),
    ("/db/", "repository"),
    ("/database/", "repository"),
]

# ---------------------------------------------------------------------------
# Inheritance-based role heuristics
# ---------------------------------------------------------------------------
# If a class's base class names include one of these, assign that role.

INHERIT_ROLE_RULES: dict[str, str] = {
    # SQLAlchemy / ORM bases → repository
    "Base": "repository",
    "DeclarativeBase": "repository",
    "Model": "repository",       # Django ORM
    # Abstract / Protocol bases → skip (not a role signal on their own)
}

# ---------------------------------------------------------------------------
# Valid layer / role values (single source of truth)
# ---------------------------------------------------------------------------

VALID_LAYERS: frozenset[str] = frozenset({
    "db", "persistence", "business_logic", "api", "ui", "util", "unknown",
})

VALID_ROLES: frozenset[str] = frozenset({
    "repository", "service", "controller", "handler", "page", "component",
    "test_helper", "util", "helper", "model", "unknown",
})
