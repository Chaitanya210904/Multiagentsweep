"""
Unit and integration tests for Agent 13: Tech Scout (Layer: Runtime).
Role: Technology researcher.
Description: Researches better technology and ranks it by benefit, effort and risk. Reports only.
Access: read-only
"""

import pytest

from agents.runtime.tech_scout_agent import TECH_SCOUT_METADATA, TechScoutAgent
from core.exceptions import UnauthorizedAccessError
from models.tech_scout import (
    PainPoint,
    StackMetadata,
    TechCategory,
    TechScoutInput,
)
from storage.registry_store import CodeRegistryStore
from tools.docs_fetch_tool import DocsFetchTool
from tools.web_search_tool import WebSearchTool


def test_tech_scout_metadata():
    """Validates that Agent 13 metadata strictly matches specifications."""
    meta = TECH_SCOUT_METADATA
    assert meta.id == "tech_scout"
    assert meta.name == "Tech Scout"
    assert meta.layer == "runtime"
    assert meta.role == "Technology researcher"
    assert meta.description == "Researches better technology and ranks it by benefit, effort and risk. Reports only."
    assert meta.access == "read-only"
    assert meta.model_tier == "medium"
    assert "stack_metadata" in meta.inputs
    assert "pain_points_from_other_agents" in meta.inputs
    assert "ranked_options_with_migration_outline" in meta.outputs
    assert meta.tools == ["web.search", "docs.fetch"]
    assert meta.trigger == "on request or scheduled"
    assert meta.optional is False


def test_read_only_access_enforcement():
    """Verifies that Tech Scout strictly enforces read-only access."""
    store = CodeRegistryStore()
    agent = TechScoutAgent(registry_store=store)

    inp = TechScoutInput(
        stack_metadata={},
        pain_points_from_other_agents=[],
    )
    out = agent.execute(inp)
    assert out is not None

    with pytest.raises(UnauthorizedAccessError):
        agent.require_access("read-write")


def test_web_search_tool_ecosystem_query():
    """Tests web.search tool querying ecosystem intelligence and package metadata."""
    tool = WebSearchTool()
    res = tool.search("FastAPI", category="framework")
    assert res.total_found >= 1
    assert any("fastapi" in item.title.lower() for item in res.items)
    item = res.items[0]
    assert item.url.startswith("https://")
    assert item.category == "framework"
    assert item.popularity_score > 5.0


def test_docs_fetch_tool_migration_guide():
    """Tests docs.fetch tool retrieving migration outlines and technical guides."""
    tool = DocsFetchTool()
    doc = tool.fetch("https://fastapi.tiangolo.com/")
    assert doc.status_code == 200
    assert "FastAPI" in doc.title or "FastAPI" in doc.content
    assert len(doc.sections) >= 1
    assert len(doc.content) > 100


def test_tech_scout_resolves_n_plus_one_query_pain_point():
    """Tests Tech Scout researching and recommending ORM upgrade for N+1 query loops."""
    store = CodeRegistryStore()
    agent = TechScoutAgent(registry_store=store)

    inp = TechScoutInput(
        stack_metadata=StackMetadata(
            languages=["Python"],
            frameworks=["Flask"],
            databases=["PostgreSQL"],
        ),
        pain_points_from_other_agents=[
            PainPoint(
                id="btnk_101",
                source_agent="scale_load",
                category="n_plus_one_query",
                description="Looped iterative queries on order_items table in orders endpoint",
            )
        ],
    )

    out = agent.execute(inp)
    assert len(out.ranked_options_with_migration_outline) >= 1
    orm_opt = next(
        (o for o in out.ranked_options_with_migration_outline if o.category == TechCategory.DATABASE_ORM),
        None,
    )
    assert orm_opt is not None
    assert "SQLAlchemy" in orm_opt.proposed_tech
    assert orm_opt.benefit_score >= 8.0
    assert any("order_items" in p for p in orm_opt.addresses_pain_points)


def test_tech_scout_resolves_caching_gap_pain_point():
    """Tests Tech Scout recommending Redis Cache-Aside for read-heavy throughput gaps."""
    store = CodeRegistryStore()
    agent = TechScoutAgent(registry_store=store)

    inp = TechScoutInput(
        pain_points_from_other_agents=[
            "High frequency repetitive SELECT queries on product catalog causing throughput deficit"
        ],
        focus_areas=["caching"],
    )

    out = agent.execute(inp)
    assert len(out.ranked_options_with_migration_outline) >= 1
    redis_opt = next(
        (o for o in out.ranked_options_with_migration_outline if o.category == TechCategory.CACHING_MESSAGING),
        None,
    )
    assert redis_opt is not None
    assert "Redis" in redis_opt.proposed_tech
    assert redis_opt.benefit_score >= 8.5
    assert redis_opt.effort_score <= 5.0
    assert redis_opt.composite_score > 0.0


def test_tech_scout_migration_outline_structure():
    """Verifies that migration outlines contain complete multi-phase roadmaps and rollback strategies."""
    store = CodeRegistryStore()
    agent = TechScoutAgent(registry_store=store)

    inp = TechScoutInput(
        pain_points_from_other_agents=["Throughput bottlenecks on synchronous WSGI requests"],
        focus_areas=["framework"],
    )
    out = agent.execute(inp)
    assert len(out.ranked_options_with_migration_outline) >= 1

    opt = out.ranked_options_with_migration_outline[0]
    outline = opt.migration_outline
    assert len(outline.phases) >= 2
    for phase in outline.phases:
        assert phase.phase_number >= 1
        assert len(phase.steps) >= 1
        assert phase.verification_criteria != ""
    assert outline.rollback_strategy != ""
    assert outline.estimated_total_effort_days >= 1


def test_end_to_end_tech_scout_pipeline():
    """Runs end-to-end Tech Scout research across multiple agent pain points and verifies ranking."""
    store = CodeRegistryStore()
    agent = TechScoutAgent(registry_store=store)

    multi_pain_points = [
        {"source_agent": "scale_load", "category": "n_plus_one_query", "description": "15x query loop on checkout"},
        {"source_agent": "scale_load", "category": "caching_gap", "description": "Uncached database reads on product items"},
        {"source_agent": "observability", "category": "latency", "description": "High latency spikes on synchronous web worker threads"},
    ]

    inp = TechScoutInput(
        stack_metadata={"languages": ["Python"], "frameworks": ["Flask"], "databases": ["PostgreSQL"]},
        pain_points_from_other_agents=multi_pain_points,
        max_options=3,
    )

    out = agent.execute(inp)
    assert len(out.ranked_options_with_migration_outline) == 3
    # Check that ranks are strictly ordered 1, 2, 3
    ranks = [o.rank for o in out.ranked_options_with_migration_outline]
    assert ranks == [1, 2, 3]
    # Check composite score monotonicity
    scores = [o.composite_score for o in out.ranked_options_with_migration_outline]
    assert scores == sorted(scores, reverse=True)
    assert out.top_recommendation is not None
    assert "Tech Scout evaluated" in out.executive_summary
