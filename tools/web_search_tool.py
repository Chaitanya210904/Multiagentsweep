"""
Tool: web.search
Tool name: web.search
Searches technical documentation, package registries, ecosystem benchmarks, and architecture guides for technology alternatives.
"""

from dataclasses import dataclass, field
import json
import re
import time
from typing import Any, Dict, List, Optional
import urllib.error
import urllib.parse
import urllib.request


@dataclass
class SearchResultItem:
    """A single technology search result item."""
    title: str
    url: str
    snippet: str
    source: str
    category: str
    package_name: Optional[str] = None
    latest_version: Optional[str] = None
    popularity_score: float = 1.0


@dataclass
class SearchResult:
    """Aggregate payload returned by web.search."""
    query: str
    total_found: int
    items: List[SearchResultItem] = field(default_factory=list)


# Curated, authoritative technical intelligence index for common modern architectures
ECOSYSTEM_INDEX: Dict[str, Dict[str, Any]] = {
    "fastapi": {
        "title": "FastAPI: High performance, easy to learn, fast to code, ready for production",
        "url": "https://fastapi.tiangolo.com/",
        "category": "framework",
        "snippet": (
            "FastAPI is a modern, fast (high-performance) web framework for building APIs with Python 3.8+ "
            "based on standard Python type hints. Built on Starlette and Pydantic. Supports async/await natively, "
            "providing ~300% throughput increase over synchronous Flask/Django WSGI servers."
        ),
        "package": "fastapi",
        "latest_version": "0.110.0",
        "popularity": 9.8,
    },
    "sqlalchemy2": {
        "title": "SQLAlchemy 2.0: The Python SQL Toolkit and Object Relational Mapper",
        "url": "https://docs.sqlalchemy.org/en/20/",
        "category": "database_orm",
        "snippet": (
            "SQLAlchemy 2.0 provides full native asyncio support (asyncpg, aiomysql, aiosqlite), "
            "type-annotated declarative models, transparent selectinload/joinedload eager loading "
            "to eliminate N+1 queries, and modern select() construct syntax."
        ),
        "package": "sqlalchemy",
        "latest_version": "2.0.28",
        "popularity": 9.6,
    },
    "redis": {
        "title": "Redis: In-memory data store used as a database, cache, streaming engine, and message broker",
        "url": "https://redis.io/docs/",
        "category": "caching_messaging",
        "snippet": (
            "Redis delivers sub-millisecond response times for read-heavy workloads. Implementing Redis "
            "Cache-Aside pattern on frequent SELECT queries relieves database connection pressure and "
            "scales throughput by 5x-20x with simple key expiry (TTL) and LRU eviction policies."
        ),
        "package": "redis",
        "latest_version": "7.2.4",
        "popularity": 9.9,
    },
    "pydantic2": {
        "title": "Pydantic V2: Data validation using Python type annotations",
        "url": "https://docs.pydantic.dev/latest/",
        "category": "framework",
        "snippet": (
            "Pydantic V2 rewrite in Rust (pydantic-core) delivers 5x to 50x faster serialization and validation. "
            "Includes strict mode, enhanced JSON schema generation, and seamless integration with modern web frameworks."
        ),
        "package": "pydantic",
        "latest_version": "2.6.4",
        "popularity": 9.7,
    },
    "httpx": {
        "title": "HTTPX: A next generation HTTP client for Python",
        "url": "https://www.python-httpx.org/",
        "category": "async_concurrency",
        "snippet": (
            "HTTPX is a fully featured HTTP client for Python 3, which provides sync and async APIs, "
            "and support for both HTTP/1.1 and HTTP/2. Replaces synchronous requests with non-blocking "
            "concurrent external API calls."
        ),
        "package": "httpx",
        "latest_version": "0.27.0",
        "popularity": 9.4,
    },
    "celery": {
        "title": "Celery: Distributed Task Queue",
        "url": "https://docs.celeryq.dev/en/stable/",
        "category": "caching_messaging",
        "snippet": (
            "Celery is an asynchronous task queue/job queue based on distributed message passing (Redis or RabbitMQ). "
            "Offloads slow computations, emails, image processing, and reporting out of the request-response hot path."
        ),
        "package": "celery",
        "latest_version": "5.3.6",
        "popularity": 9.3,
    },
    "uvicorn": {
        "title": "Uvicorn: The lightning-fast ASGI server",
        "url": "https://www.uvicorn.org/",
        "category": "tooling_infra",
        "snippet": (
            "Uvicorn is an ASGI web server implementation for Python based on uvloop and httptools. "
            "Enables non-blocking event-loop request processing with standard Gunicorn worker management."
        ),
        "package": "uvicorn",
        "latest_version": "0.29.0",
        "popularity": 9.5,
    },
    "alembic": {
        "title": "Alembic: Lightweight database migration tool for SQLAlchemy",
        "url": "https://alembic.sqlalchemy.org/en/latest/",
        "category": "database_orm",
        "snippet": (
            "Alembic provides transactional schema migrations, auto-generation of revision scripts "
            "from SQLAlchemy metadata, and branch merges for multi-developer migrations."
        ),
        "package": "alembic",
        "latest_version": "1.13.1",
        "popularity": 9.4,
    },
}


class WebSearchTool:
    """Tool for researching software libraries, benchmarks, and architecture patterns."""

    name = "web.search"
    description = (
        "Searches technical documentation, package registries, ecosystem benchmarks, "
        "and architecture guides for technology alternatives."
    )

    def __init__(self, enable_live_registry_lookup: bool = True):
        self.enable_live_registry_lookup = enable_live_registry_lookup

    def search(self, query: str, category: Optional[str] = None, max_results: int = 5) -> SearchResult:
        """
        Searches technical ecosystem knowledge base and live package registries (PyPI).
        """
        items: List[SearchResultItem] = []
        tokens = [t.lower() for t in re.findall(r"[a-zA-Z0-9_\-]+", query)]

        # 1. Search ecosystem index
        for key, entry in ECOSYSTEM_INDEX.items():
            if category and entry["category"] != category:
                continue

            entry_tokens = set(re.findall(r"[a-zA-Z0-9_\-]+", (key + " " + entry["title"] + " " + entry["snippet"]).lower()))
            matches = sum(1 for t in tokens if t in entry_tokens or any(t in et for et in entry_tokens))
            if matches > 0:
                score = entry["popularity"] + matches * 0.5
                items.append(
                    SearchResultItem(
                        title=entry["title"],
                        url=entry["url"],
                        snippet=entry["snippet"],
                        source="ecosystem_knowledge_index",
                        category=entry["category"],
                        package_name=entry.get("package"),
                        latest_version=entry.get("latest_version"),
                        popularity_score=round(score, 2),
                    )
                )

        # 2. If live query specifies a package name, attempt live PyPI registry check
        if self.enable_live_registry_lookup and len(tokens) == 1 and not items:
            pypi_item = self._query_pypi(tokens[0])
            if pypi_item:
                items.append(pypi_item)

        # Sort items by popularity/relevance
        items.sort(key=lambda x: -x.popularity_score)
        selected = items[:max_results]

        return SearchResult(
            query=query,
            total_found=len(selected),
            items=selected,
        )

    def _query_pypi(self, package_name: str) -> Optional[SearchResultItem]:
        """Queries PyPI JSON API for package metadata with fast timeout."""
        url = f"https://pypi.org/pypi/{urllib.parse.quote(package_name)}/json"
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "multiagent-tech-scout/1.0"},
            )
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                info = data.get("info", {})
                return SearchResultItem(
                    title=f"{info.get('name')}: {info.get('summary', 'Python package')}",
                    url=info.get("package_url", url),
                    snippet=info.get("summary", ""),
                    source="pypi_registry",
                    category="library",
                    package_name=info.get("name"),
                    latest_version=info.get("version"),
                    popularity_score=8.0,
                )
        except Exception:
            return None
