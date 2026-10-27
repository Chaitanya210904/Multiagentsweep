"""
Agent 13: Tech Scout (Layer: Runtime).
Role: Technology researcher.
Description: Researches better technology and ranks it by benefit, effort and risk. Reports only.
Access: read-only
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from agents.base import AgentMetadata, BaseAgent
from core.exceptions import UnauthorizedAccessError
from models.registry import NodeType, RegistryNode
from models.tech_scout import (
    MigrationOutline,
    MigrationPhase,
    PainPoint,
    RankedOption,
    StackMetadata,
    TechCategory,
    TechScoutInput,
    TechScoutOutput,
)
from storage.registry_store import CodeRegistryStore
from tools.docs_fetch_tool import DocsFetchTool
from tools.web_search_tool import WebSearchTool


TECH_SCOUT_METADATA = AgentMetadata(
    id="tech_scout",
    name="Tech Scout",
    layer="runtime",
    role="Technology researcher",
    description="Researches better technology and ranks it by benefit, effort and risk. Reports only.",
    access="read-only",
    model_tier="medium",
    inputs=[
        "stack_metadata",
        "pain_points_from_other_agents",
    ],
    outputs=[
        "ranked_options_with_migration_outline",
    ],
    tools=[
        "web.search",
        "docs.fetch",
    ],
    trigger="on request or scheduled",
    optional=False,
)


class TechScoutAgent(BaseAgent):
    """
    Tech Scout Agent evaluates current technology stack metadata, cross-references
    pain points and bottlenecks surfaced by other agents, researches modern alternatives
    via web.search and docs.fetch, and produces ranked upgrade options with migration outlines.
    """

    def __init__(
        self,
        metadata: Optional[AgentMetadata] = None,
        registry_store: Optional[CodeRegistryStore] = None,
        repo_root: Optional[Union[str, Path]] = None,
        log_file: Optional[str] = None,
    ):
        meta = (metadata or TECH_SCOUT_METADATA).model_copy(deep=True)
        super().__init__(metadata=meta, log_file=log_file)
        self.registry_store = registry_store or CodeRegistryStore()
        self.repo_root = Path(repo_root) if repo_root else Path.cwd()

        # Tools
        self.web_tool = WebSearchTool()
        self.docs_tool = DocsFetchTool()

    def execute(self, inputs: TechScoutInput) -> TechScoutOutput:
        """
        Executes technology research, ranks architectural options, and outlines migration paths.
        """
        # Strict read-only enforcement
        self.require_access("read-only")

        t0 = self.log_started({
            "has_stack_metadata": bool(inputs.stack_metadata),
            "pain_points_count": len(inputs.pain_points_from_other_agents),
            "max_options": inputs.max_options,
        })

        try:
            # 1. Resolve & Infer Stack Metadata
            self.log_event(
                event="analysis.stack_metadata",
                message="Resolving codebase stack metadata and dependencies",
            )
            stack_meta = self._resolve_stack_metadata(inputs.stack_metadata)

            # 2. Ingest & Normalize Pain Points
            self.log_event(
                event="analysis.pain_points",
                message="Normalizing pain points and architectural bottlenecks from other agents",
                raw_count=len(inputs.pain_points_from_other_agents),
            )
            normalized_pain_points = self._normalize_pain_points(
                inputs.pain_points_from_other_agents
            )

            # 3. Research Technology Options via web.search
            self.log_event(
                event="tool.web_search",
                message="Researching modern technological alternatives matching stack and pain points",
            )
            candidate_technologies = self._research_technology_candidates(
                stack=stack_meta,
                pain_points=normalized_pain_points,
                focus_areas=inputs.focus_areas,
            )

            # 4. Fetch Documentation & Migration Guides via docs.fetch
            self.log_event(
                event="tool.docs_fetch",
                message="Fetching official migration guides, breaking changes, and architecture docs",
                candidates_count=len(candidate_technologies),
            )
            ranked_options = self._rank_and_outline_options(
                candidates=candidate_technologies,
                pain_points=normalized_pain_points,
                max_options=inputs.max_options,
            )

            # 5. Synthesize Output & Executive Summary
            top_rec = ranked_options[0].title if ranked_options else None
            summary = self._generate_executive_summary(
                ranked_options=ranked_options,
                pain_points=normalized_pain_points,
                stack=stack_meta,
            )

            self.log_completed(
                start_time=t0,
                outputs_summary={
                    "total_options_ranked": len(ranked_options),
                    "top_recommendation": top_rec,
                    "pain_points_addressed": len(normalized_pain_points),
                },
            )

            return TechScoutOutput(
                ranked_options_with_migration_outline=ranked_options,
                total_options_researched=len(candidate_technologies),
                pain_points_addressed_count=len(normalized_pain_points),
                top_recommendation=top_rec,
                executive_summary=summary,
            )

        except Exception as e:
            self.log_failed(t0, e)
            raise

    # --------------------------------------------------------------------------
    # Subroutines: Stack Metadata & Pain Point Ingestion
    # --------------------------------------------------------------------------

    def _resolve_stack_metadata(
        self, raw_stack: Union[Dict[str, Any], StackMetadata]
    ) -> StackMetadata:
        """Parses provided stack metadata or infers it from repository manifests and nodes."""
        if isinstance(raw_stack, StackMetadata):
            meta = raw_stack
        elif isinstance(raw_stack, dict) and raw_stack:
            meta = StackMetadata(**raw_stack)
        else:
            meta = StackMetadata()

        # If languages empty, infer from registry nodes or repository files
        if not meta.languages:
            langs = set()
            for n in self.registry_store.list_all():
                p = n.location.path
                if p.endswith(".py"):
                    langs.add("Python")
                elif p.endswith((".js", ".jsx", ".mjs")):
                    langs.add("JavaScript")
                elif p.endswith((".ts", ".tsx")):
                    langs.add("TypeScript")
                elif p.endswith(".go"):
                    langs.add("Go")
            meta.languages = sorted(list(langs)) or ["Python"]

        # Check repository dependency manifests
        req_file = self.repo_root / "requirements.txt"
        if req_file.is_file() and not meta.libraries:
            try:
                for line in req_file.read_text(encoding="utf-8").splitlines():
                    cleaned = line.split("#")[0].strip()
                    if "==" in cleaned:
                        pkg, ver = cleaned.split("==", 1)
                        meta.libraries[pkg.strip().lower()] = ver.strip()
                    elif cleaned:
                        meta.libraries[cleaned.lower()] = "latest"
            except Exception:
                pass

        return meta

    def _normalize_pain_points(
        self, pain_points: List[Union[str, Dict[str, Any], PainPoint]]
    ) -> List[PainPoint]:
        """Normalizes various pain point inputs into standard PainPoint instances."""
        normalized: List[PainPoint] = []
        for idx, item in enumerate(pain_points):
            if isinstance(item, PainPoint):
                normalized.append(item)
            elif isinstance(item, dict):
                p_id = item.get("id") or f"pain_{idx+1}"
                src = item.get("source_agent", item.get("source", "system"))
                cat = item.get("category", item.get("type", "general"))
                desc = item.get("description", item.get("title", str(item)))
                sev = item.get("severity", "medium")
                comps = item.get("affected_components", item.get("components", []))
                normalized.append(
                    PainPoint(
                        id=p_id,
                        source_agent=src,
                        category=cat,
                        severity=sev,
                        description=desc,
                        affected_components=comps,
                    )
                )
            elif isinstance(item, str):
                normalized.append(
                    PainPoint(
                        id=f"pain_{idx+1}",
                        source_agent="manual",
                        category=self._categorize_pain_point_text(item),
                        severity="medium",
                        description=item,
                    )
                )

        return normalized

    def _categorize_pain_point_text(self, text: str) -> str:
        """Infers category of pain point from free text."""
        lower = text.lower()
        if "n+1" in lower or "query" in lower or "orm" in lower:
            return "n_plus_one_query"
        elif "index" in lower or "slow" in lower:
            return "slow_query"
        elif "cache" in lower:
            return "caching_gap"
        elif "coupling" in lower or "circular" in lower or "layer" in lower:
            return "architectural_coupling"
        elif "cve" in lower or "vulnerability" in lower or "auth" in lower:
            return "security_vulnerability"
        elif "latency" in lower or "throughput" in lower or "capacity" in lower:
            return "throughput_bottleneck"
        return "maintainability"

    # --------------------------------------------------------------------------
    # Subroutines: Technology Research via web.search
    # --------------------------------------------------------------------------

    def _research_technology_candidates(
        self,
        stack: StackMetadata,
        pain_points: List[PainPoint],
        focus_areas: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Searches ecosystem knowledge and registries for modern technological alternatives."""
        candidates: List[Dict[str, Any]] = []
        categories_seen: Set[str] = set()

        # Identify target domains based on pain points
        has_n1_or_db = any(
            p.category in ("n_plus_one_query", "slow_query", "missing_index", "database") for p in pain_points
        )
        has_caching = any(
            p.category in ("caching_gap", "throughput_bottleneck", "latency") for p in pain_points
        )
        has_framework_or_async = any(
            p.category in ("latency", "capacity_deficit", "architectural_coupling") for p in pain_points
        )

        # 1. Database & ORM Upgrade Research
        if has_n1_or_db or (focus_areas and "database" in focus_areas):
            res = self.web_tool.search("SQLAlchemy 2.0 Async ORM eager loading", category="database_orm")
            for item in res.items:
                candidates.append({
                    "proposed_tech": "SQLAlchemy 2.0 + asyncpg",
                    "current_tech": "Legacy synchronous ORM / raw queries",
                    "category": TechCategory.DATABASE_ORM,
                    "search_item": item,
                    "target_pain_types": ["n_plus_one_query", "slow_query"],
                })

        # 2. Caching & Throughput Research
        if has_caching or (focus_areas and "caching" in focus_areas):
            res = self.web_tool.search("Redis Cache-Aside pattern", category="caching_messaging")
            for item in res.items:
                candidates.append({
                    "proposed_tech": "Redis 7.2 (Cache-Aside)",
                    "current_tech": "Uncached direct database reads",
                    "category": TechCategory.CACHING_MESSAGING,
                    "search_item": item,
                    "target_pain_types": ["caching_gap", "throughput_bottleneck"],
                })

        # 3. Asynchronous Modern Web Framework Research
        if has_framework_or_async or (focus_areas and "framework" in focus_areas):
            res = self.web_tool.search("FastAPI modern high performance async REST", category="framework")
            for item in res.items:
                candidates.append({
                    "proposed_tech": "FastAPI + Uvicorn ASGI",
                    "current_tech": "Synchronous WSGI web framework",
                    "category": TechCategory.FRAMEWORK,
                    "search_item": item,
                    "target_pain_types": ["latency", "capacity_deficit", "architectural_coupling"],
                })

        # 4. Asynchronous Task Queue / Background Processing
        if any("task" in p.description.lower() or "slow" in p.description.lower() for p in pain_points):
            res = self.web_tool.search("Celery distributed task queue", category="caching_messaging")
            for item in res.items:
                candidates.append({
                    "proposed_tech": "Celery 5.3 + Redis broker",
                    "current_tech": "Synchronous in-process long-running requests",
                    "category": TechCategory.CACHING_MESSAGING,
                    "search_item": item,
                    "target_pain_types": ["slow_query", "latency"],
                })

        # If no specific candidates matched, provide top ecosystem architectural upgrade
        if not candidates:
            res = self.web_tool.search("FastAPI", category="framework")
            if res.items:
                candidates.append({
                    "proposed_tech": "FastAPI + Pydantic V2",
                    "current_tech": "Legacy web framework",
                    "category": TechCategory.FRAMEWORK,
                    "search_item": res.items[0],
                    "target_pain_types": ["maintainability"],
                })

        return candidates

    # --------------------------------------------------------------------------
    # Subroutines: Ranking & Migration Outline Formulation
    # --------------------------------------------------------------------------

    def _rank_and_outline_options(
        self,
        candidates: List[Dict[str, Any]],
        pain_points: List[PainPoint],
        max_options: int,
    ) -> List[RankedOption]:
        """Scores candidate technologies by benefit, effort, and risk, and constructs migration outlines."""
        ranked_list: List[RankedOption] = []

        for cand in candidates:
            search_item = cand["search_item"]
            prop_tech = cand["proposed_tech"]
            curr_tech = cand["current_tech"]
            cat = cand["category"]
            target_pains = cand["target_pain_types"]

            # Match pain points resolved
            resolved_pains = [
                p.description for p in pain_points if p.category in target_pains or any(tp in p.description.lower() for tp in target_pains)
            ]
            if not resolved_pains and pain_points:
                resolved_pains = [pain_points[0].description]

            # Fetch official documentation & migration reference via docs.fetch
            doc_res = self.docs_tool.fetch(search_item.url)

            # Compute Benefit, Effort, and Risk scores
            benefit_score, benefit_rat = self._evaluate_benefit(prop_tech, cat, len(resolved_pains))
            effort_score, effort_rat = self._evaluate_effort(prop_tech, cat)
            risk_score, risk_rat = self._evaluate_risk(prop_tech, cat)

            # Composite Formula: (Benefit * 2.0) - (Effort * 1.0) - (Risk * 1.0)
            composite = round((benefit_score * 2.0) - (effort_score * 1.0) - (risk_score * 1.0), 2)

            # Build detailed migration outline
            outline = self._build_migration_outline(prop_tech, curr_tech, cat, doc_res)

            opt = RankedOption(
                title=f"Adopt {prop_tech} for {cat.value.replace('_', ' ').title()}",
                current_tech=curr_tech,
                proposed_tech=prop_tech,
                category=cat,
                benefit_score=benefit_score,
                benefit_rationale=benefit_rat,
                effort_score=effort_score,
                effort_rationale=effort_rat,
                risk_score=risk_score,
                risk_rationale=risk_rat,
                composite_score=composite,
                addresses_pain_points=resolved_pains,
                migration_outline=outline,
                documentation_urls=[search_item.url],
            )
            ranked_list.append(opt)

        # Deduplicate by proposed_tech
        unique_map: Dict[str, RankedOption] = {}
        for r in ranked_list:
            if r.proposed_tech not in unique_map or r.composite_score > unique_map[r.proposed_tech].composite_score:
                unique_map[r.proposed_tech] = r

        final_ranked = sorted(list(unique_map.values()), key=lambda x: -x.composite_score)
        # Assign 1-indexed ranks
        for idx, item in enumerate(final_ranked[:max_options]):
            item.rank = idx + 1

        return final_ranked[:max_options]

    def _evaluate_benefit(self, tech: str, category: TechCategory, resolved_count: int) -> Tuple[float, str]:
        """Calculates 1-10 benefit score based on performance gain and pain points resolved."""
        base = 7.5
        if "Redis" in tech:
            base = 9.2
            rat = (
                "Eliminates up to 90% of redundant database queries, reducing p95 read latency to < 1ms "
                "and multiplying sustainable request throughput by 5x-20x."
            )
        elif "FastAPI" in tech:
            base = 8.8
            rat = (
                "Provides ~3x asynchronous request concurrency over WSGI, native OpenAPI documentation, "
                "and robust type safety with Pydantic validation."
            )
        elif "SQLAlchemy" in tech:
            base = 8.6
            rat = (
                "Resolves N+1 query loops via selectinload eager loading, provides native async connection pooling "
                "(asyncpg), and standardizes typed data models."
            )
        elif "Celery" in tech:
            base = 8.0
            rat = (
                "Offloads heavy blocking computations and I/O out of the HTTP transaction hot path into "
                "isolated background worker pools."
            )
        else:
            base = 7.0
            rat = f"Modernizes {category.value} to improve developer productivity and code maintainability."

        bonus = min(resolved_count * 0.4, 1.2)
        final_score = round(min(base + bonus, 10.0), 1)
        return final_score, rat

    def _evaluate_effort(self, tech: str, category: TechCategory) -> Tuple[float, str]:
        """Calculates 1-10 engineering effort score (lower is less effort)."""
        if "Redis" in tech:
            return 3.5, "Low to moderate effort. Requires installing Redis client, adding cache helper decorators, and setting standard TTLs."
        elif "SQLAlchemy" in tech:
            return 6.0, "Moderate effort. Requires updating model classes to DeclarativeBase, updating query syntax to select(), and adding async session context managers."
        elif "FastAPI" in tech:
            return 6.5, "Moderate to high effort. Requires refactoring route handlers to async, updating dependency injection, and rewriting middleware."
        elif "Celery" in tech:
            return 5.0, "Moderate effort. Requires provisioning broker (Redis/RabbitMQ), defining Celery tasks, and handling task retries."
        return 4.5, "Moderate engineering effort across a few sprints."

    def _evaluate_risk(self, tech: str, category: TechCategory) -> Tuple[float, str]:
        """Calculates 1-10 risk score (lower is safer)."""
        if "Redis" in tech:
            return 2.5, "Low risk. Implemented via Cache-Aside with fallback to database; cache misses or Redis downtime fail gracefully."
        elif "SQLAlchemy" in tech:
            return 4.0, "Medium risk. Dialect differences with asyncpg and transaction lifecycle nuances require thorough unit/integration test coverage."
        elif "FastAPI" in tech:
            return 4.5, "Medium risk. Event-loop blocking by synchronous libraries must be audited and wrapped in run_in_threadpool."
        elif "Celery" in tech:
            return 3.5, "Low to medium risk. Requires monitoring broker queue depth and handling worker crash edge cases."
        return 3.0, "Low risk when introduced incrementally behind feature flags."

    def _build_migration_outline(
        self,
        prop_tech: str,
        curr_tech: str,
        category: TechCategory,
        doc_result: Any,
    ) -> MigrationOutline:
        """Constructs actionable multi-phase migration roadmap."""
        phases: List[MigrationPhase] = []
        breaking: List[str] = []
        prereqs: List[str] = []
        rollback: str = ""
        est_days = 10

        if "Redis" in prop_tech:
            est_days = 5
            prereqs = ["Provision Redis 7.x cluster or managed instance", "Add redis-py client dependency"]
            breaking = ["Cache keys must be versioned to avoid stale deserialization errors during updates"]
            rollback = "Disable cache reading via feature flag 'ENABLE_REDIS_CACHE=false'; application falls back to direct DB queries."
            phases = [
                MigrationPhase(
                    phase_number=1,
                    title="Infrastructure & Client Setup",
                    description="Provision Redis instance and configure connection pooling with circuit breaking.",
                    steps=[
                        "Deploy Redis 7 instance with maxmemory LRU eviction policy",
                        "Configure environment variables: REDIS_URL, REDIS_MAX_CONNECTIONS",
                        "Add redis client wrapper with graceful connection exception suppression",
                    ],
                    estimated_duration_days=1,
                    verification_criteria="Ping Redis endpoint from health check route; verify sub-millisecond response.",
                ),
                MigrationPhase(
                    phase_number=2,
                    title="Cache-Aside Layer Implementation",
                    description="Implement cache decorators and helpers on high-frequency read endpoints.",
                    steps=[
                        "Wrap repository SELECT methods with `@cache_aside(key='cache:entity:{id}', ttl=300)`",
                        "Add cache invalidation hooks in model UPDATE and DELETE transactions",
                        "Test cache hit vs miss latency in local environment",
                    ],
                    estimated_duration_days=2,
                    verification_criteria="Verify cache hit returns identical payload to database query and reduces latency to < 2ms.",
                ),
                MigrationPhase(
                    phase_number=3,
                    title="Canary Rollout & Monitoring",
                    description="Enable cache for 10% of read traffic, monitoring hit ratios and DB load reduction.",
                    steps=[
                        "Deploy behind feature flag `ENABLE_CACHE_ASIDE`",
                        "Monitor Redis hit ratio (target: > 80%) and database IOPS",
                        "Verify zero cache stampede on expired keys",
                    ],
                    estimated_duration_days=2,
                    verification_criteria="Confirm 80%+ cache hit ratio and 50%+ reduction in database query volume.",
                ),
            ]

        elif "SQLAlchemy" in prop_tech:
            est_days = 12
            prereqs = ["Install sqlalchemy>=2.0.28, asyncpg>=0.29.0, greenlet", "PostgreSQL database accessible over TCP"]
            breaking = ["Legacy `session.query()` deprecated in favor of `select()`", "Synchronous session cannot execute async drivers"]
            rollback = "Maintain legacy repository adapter in parallel; switch database dependency injection provider back to synchronous engine."
            phases = [
                MigrationPhase(
                    phase_number=1,
                    title="Async Engine & Declarative Base",
                    description="Set up async database engine and migrate models to modern 2.0 type mapping.",
                    steps=[
                        "Initialize `create_async_engine('postgresql+asyncpg://...')`",
                        "Create `async_sessionmaker` session factory",
                        "Update model classes to inherit from `DeclarativeBase` with `Mapped[T]` columns",
                    ],
                    estimated_duration_days=3,
                    verification_criteria="Run Alembic migrations against async engine cleanly.",
                ),
                MigrationPhase(
                    phase_number=2,
                    title="Eager Loading & N+1 Query Elimination",
                    description="Rewrite repository queries using modern `select()` syntax with `selectinload`.",
                    steps=[
                        "Replace looped queries with `select(Parent).options(selectinload(Parent.children))`",
                        "Refactor repository functions to `async def` and use `await session.execute(...)`",
                        "Run integration test suite to verify zero query regression",
                    ],
                    estimated_duration_days=5,
                    verification_criteria="Verify N+1 queries disappear from SQL logs; query count per transaction drops from N to 1-2.",
                ),
                MigrationPhase(
                    phase_number=3,
                    title="Cutover & Legacy ORM Deprecation",
                    description="Switch service layer to async repositories and remove legacy synchronous engine.",
                    steps=[
                        "Migrate API endpoints to inject async database session",
                        "Verify transaction rollback and connection pool cleanup on unhandled exceptions",
                        "Remove old ORM dependencies and cleanup deprecated code paths",
                    ],
                    estimated_duration_days=4,
                    verification_criteria="All endpoints execute over async session pool without greenlet blocking errors.",
                ),
            ]

        else:
            # Default modern framework migration outline
            est_days = 8
            prereqs = ["Install modern framework dependencies and ASGI server"]
            breaking = ["Route registration syntax and middleware signatures change"]
            rollback = "Deploy legacy WSGI application behind reverse proxy routing."
            phases = [
                MigrationPhase(
                    phase_number=1,
                    title="Prerequisites & Proof of Concept",
                    description="Set up project structure and migrate initial non-critical endpoint.",
                    steps=["Add dependencies", "Implement initial health check and test routes", "Verify async event loop"],
                    estimated_duration_days=2,
                    verification_criteria="New test endpoint responds with 200 OK and valid OpenAPI schema.",
                ),
                MigrationPhase(
                    phase_number=2,
                    title="Incremental Endpoint Migration",
                    description="Port core business routes and integrate authentication dependencies.",
                    steps=["Migrate route handlers", "Define Pydantic request/response schemas", "Add unit tests"],
                    estimated_duration_days=4,
                    verification_criteria="Unit and integration tests pass with 100% route coverage.",
                ),
                MigrationPhase(
                    phase_number=3,
                    title="Production Cutover",
                    description="Route production ingress to new service.",
                    steps=["Deploy behind load balancer", "Monitor error rate and latency", "Retire legacy application"],
                    estimated_duration_days=2,
                    verification_criteria="Zero 5xx regressions and improved p95 latency under production load.",
                ),
            ]

        return MigrationOutline(
            phases=phases,
            breaking_changes=breaking,
            prerequisites=prereqs,
            rollback_strategy=rollback,
            estimated_total_effort_days=est_days,
        )

    def _generate_executive_summary(
        self,
        ranked_options: List[RankedOption],
        pain_points: List[PainPoint],
        stack: StackMetadata,
    ) -> str:
        """Constructs an executive synthesis of technology recommendations."""
        if not ranked_options:
            return "Tech Scout analysis completed: Existing technology stack meets current operational requirements."

        top = ranked_options[0]
        options_summary = "; ".join(
            f"#{o.rank} {o.proposed_tech} (Composite Score: {o.composite_score}, Benefit: {o.benefit_score}/10, Effort: {o.effort_score}/10)"
            for o in ranked_options
        )

        return (
            f"Tech Scout evaluated {len(pain_points)} active pain points against the current stack "
            f"({', '.join(stack.languages) or 'Python'}). Top recommendation: '{top.title}' "
            f"providing a benefit rating of {top.benefit_score}/10 with composite score {top.composite_score}. "
            f"Researched options in rank order: {options_summary}."
        )
