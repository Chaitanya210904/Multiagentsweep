"""
Tool: docs.fetch
Tool name: docs.fetch
Fetches official technical documentation, migration guides, changelogs, and release notes from URLs or local files.
"""

from dataclasses import dataclass, field
import html
from pathlib import Path
import re
from typing import Any, Dict, List, Optional
import urllib.error
import urllib.request


@dataclass
class DocResult:
    """Document payload returned by docs.fetch."""
    url_or_path: str
    title: str
    content: str
    sections: List[str] = field(default_factory=list)
    status_code: int = 200
    is_fallback: bool = False


# Authoritative fallback docs for core architectural migrations
MIGRATION_DOCS_STORE: Dict[str, Dict[str, Any]] = {
    "fastapi": {
        "title": "FastAPI Migration & Architecture Guide",
        "sections": ["Overview", "Dependency Injection", "Async Endpoints", "Pydantic Schemas", "Performance"],
        "content": (
            "# FastAPI Migration & Architecture Guide\n\n"
            "## Overview\n"
            "FastAPI is a modern web framework designed for asynchronous, high-throughput REST APIs.\n\n"
            "## Key Advantages\n"
            "- Asynchronous event loop native support via Starlette and Uvicorn\n"
            "- Automatic OpenAPI and Swagger UI interactive documentation\n"
            "- Type-safe request and response validation via Pydantic\n"
            "- Built-in dependency injection for database sessions, auth, and config\n\n"
            "## Migration Steps from Flask/WSGI\n"
            "1. Replace `Flask(__name__)` with `FastAPI()`\n"
            "2. Convert `@app.route('/path', methods=['GET'])` to `@app.get('/path')`\n"
            "3. Switch endpoint functions from `def handler()` to `async def handler()`\n"
            "4. Define request payloads using Pydantic `BaseModel` instead of `request.json`\n"
            "5. Inject database sessions using `Depends(get_db_session)`"
        ),
    },
    "sqlalchemy2": {
        "title": "SQLAlchemy 2.0 Async Migration Guide",
        "sections": ["Overview", "Async Engine", "Declarative Models", "Query Syntax", "Eager Loading"],
        "content": (
            "# SQLAlchemy 2.0 Async Migration Guide\n\n"
            "## Overview\n"
            "SQLAlchemy 2.0 modernizes the ORM with pure typing and first-class async engine support.\n\n"
            "## Key Upgrades\n"
            "- Async engine and session: `create_async_engine('postgresql+asyncpg://...')`\n"
            "- Eliminates legacy `session.query(Model)` in favor of `select(Model)`\n"
            "- Resolves N+1 queries using `selectinload` and `joinedload` options\n"
            "- DeclarativeBase with `Mapped[int] = mapped_column()` typing\n\n"
            "## Migration Steps\n"
            "1. Update dialect driver to asyncpg (`postgresql+asyncpg://`)\n"
            "2. Wrap database access in `async with async_session() as session:`\n"
            "3. Replace `filter_by(...)` with `execute(select(Model).where(...))`\n"
            "4. Add `.options(selectinload(Model.relation))` to eagerly load related collections."
        ),
    },
    "redis": {
        "title": "Redis Cache-Aside Pattern Implementation Guide",
        "sections": ["Pattern Overview", "Cache Keys", "TTL Strategy", "Invalidation", "Resilience"],
        "content": (
            "# Redis Cache-Aside Pattern Implementation Guide\n\n"
            "## Overview\n"
            "Cache-Aside (Lazy Loading) stores read-heavy entity representations in Redis to protect the primary DB.\n\n"
            "## Workflow\n"
            "1. Application checks Redis for key `cache:{entity}:{id}`\n"
            "2. On Cache Hit: returns cached JSON payload immediately (< 1ms)\n"
            "3. On Cache Miss: queries primary SQL database, serializes to JSON, writes to Redis with TTL, returns data\n\n"
            "## Invalidation & TTL\n"
            "- Set standard TTL (e.g. 300s - 3600s) to guarantee eventual consistency\n"
            "- On entity UPDATE or DELETE, synchronously delete Redis key: `redis.delete(key)`\n"
            "- Implement Circuit Breaker fallback to primary DB if Redis connection drops."
        ),
    },
}


class DocsFetchTool:
    """Tool for fetching official documentation, changelogs, and migration guides."""

    name = "docs.fetch"
    description = (
        "Fetches official technical documentation, migration guides, changelogs, "
        "and release notes from URLs or local documentation files."
    )

    def fetch(self, url_or_path: str, timeout: float = 2.0) -> DocResult:
        """
        Fetches doc text from URL or local file, falling back to curated reference docs.
        """
        # 1. Check local file path
        local_p = Path(url_or_path)
        if local_p.is_file():
            try:
                text = local_p.read_text(encoding="utf-8")
                sections = [line.strip("# ").strip() for line in text.splitlines() if line.startswith("#")]
                return DocResult(
                    url_or_path=url_or_path,
                    title=sections[0] if sections else local_p.name,
                    content=text,
                    sections=sections,
                    status_code=200,
                )
            except Exception:
                pass

        # 2. Check curated store first if URL contains known library keys
        lower_ref = url_or_path.lower()
        matched_key = next((k for k in MIGRATION_DOCS_STORE if k in lower_ref), None)

        # 3. If it looks like a remote HTTP URL, attempt fetch
        if url_or_path.startswith(("http://", "https://")):
            try:
                req = urllib.request.Request(
                    url_or_path,
                    headers={"User-Agent": "Mozilla/5.0 (multiagent-tech-scout/1.0)"},
                )
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    raw_bytes = resp.read()
                    charset = resp.headers.get_content_charset() or "utf-8"
                    html_text = raw_bytes.decode(charset, errors="replace")
                    clean_text, title = self._clean_html(html_text)
                    sections = [line.strip("# ").strip() for line in clean_text.splitlines() if line.startswith("#")]
                    return DocResult(
                        url_or_path=url_or_path,
                        title=title or url_or_path,
                        content=clean_text,
                        sections=sections,
                        status_code=resp.status,
                        is_fallback=False,
                    )
            except Exception:
                # Fall through to curated fallback
                pass

        # 4. Fallback to curated reference docs
        if matched_key and matched_key in MIGRATION_DOCS_STORE:
            stored = MIGRATION_DOCS_STORE[matched_key]
            return DocResult(
                url_or_path=url_or_path,
                title=stored["title"],
                content=stored["content"],
                sections=stored["sections"],
                status_code=200,
                is_fallback=True,
            )

        # Generic summary fallback
        return DocResult(
            url_or_path=url_or_path,
            title=f"Documentation for {url_or_path}",
            content=f"Technical specification and reference manual for {url_or_path}.",
            sections=["Overview", "Architecture"],
            status_code=200,
            is_fallback=True,
        )

    def _clean_html(self, raw_html: str) -> (str, Optional[str]):
        """Strips scripts, styles, and tags from HTML text, extracting clean markdown text."""
        # Extract title
        title_m = re.search(r"<title[^>]*>(.*?)</title>", raw_html, re.IGNORECASE | re.DOTALL)
        title = html.unescape(title_m.group(1).strip()) if title_m else None

        # Remove scripts, styles, header, footer, nav
        cleaned = re.sub(r"<(?:script|style|nav|header|footer)[^>]*>.*?</(?:script|style|nav|header|footer)>", "", raw_html, flags=re.IGNORECASE | re.DOTALL)
        # Convert <h1>, <h2>, <h3> to markdown
        cleaned = re.sub(r"<h1[^>]*>(.*?)</h1>", r"\n# \1\n", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"<h2[^>]*>(.*?)</h2>", r"\n## \1\n", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"<h3[^>]*>(.*?)</h3>", r"\n### \1\n", cleaned, flags=re.IGNORECASE)
        # Strip all other HTML tags
        cleaned = re.sub(r"<[^>]+>", " ", cleaned)
        # Unescape HTML entities
        cleaned = html.unescape(cleaned)
        # Collapse multiple blank lines
        cleaned = re.sub(r"\n\s*\n+", "\n\n", cleaned).strip()
        return cleaned, title
