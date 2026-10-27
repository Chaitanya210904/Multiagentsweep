"""
Data models for Agent 13: Tech Scout (Layer: Runtime).
Role: Technology researcher.
Description: Researches better technology and ranks it by benefit, effort and risk. Reports only.
Access: read-only
"""

from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import uuid

from pydantic import BaseModel, Field


class TechCategory(str, Enum):
    """Categories of technological upgrades or replacements."""
    FRAMEWORK = "framework"
    DATABASE_ORM = "database_orm"
    CACHING_MESSAGING = "caching_messaging"
    ASYNC_CONCURRENCY = "async_concurrency"
    OBSERVABILITY_TELEMETRY = "observability_telemetry"
    TESTING_BENCHMARKING = "testing_benchmarking"
    SECURITY_AUTH = "security_auth"
    TOOLING_INFRA = "tooling_infra"


class MigrationPhase(BaseModel):
    """A distinct milestone in a multi-step technology migration."""
    phase_number: int = Field(ge=1)
    title: str
    description: str
    steps: List[str] = Field(default_factory=list)
    estimated_duration_days: Optional[int] = Field(default=None, ge=1)
    verification_criteria: str


class MigrationOutline(BaseModel):
    """Detailed step-by-step roadmap for migrating to a proposed technology."""
    phases: List[MigrationPhase] = Field(default_factory=list)
    breaking_changes: List[str] = Field(default_factory=list)
    prerequisites: List[str] = Field(default_factory=list)
    rollback_strategy: str
    estimated_total_effort_days: int = Field(default=5, ge=1)


class RankedOption(BaseModel):
    """A researched technological alternative ranked by benefit, effort, and risk."""
    id: str = Field(default_factory=lambda: f"opt_{uuid.uuid4().hex[:8]}")
    rank: int = Field(default=1, ge=1)
    title: str
    current_tech: str
    proposed_tech: str
    category: TechCategory
    benefit_score: float = Field(
        ge=0.0, le=10.0, description="1-10 benefit score (higher = greater advantage)"
    )
    benefit_rationale: str
    effort_score: float = Field(
        ge=0.0, le=10.0, description="1-10 effort score (higher = more work required)"
    )
    effort_rationale: str
    risk_score: float = Field(
        ge=0.0, le=10.0, description="1-10 risk score (higher = greater risk/breakage)"
    )
    risk_rationale: str
    composite_score: float = Field(
        description="Composite ranking score: (benefit * 2.0) - (effort * 1.0) - (risk * 1.0)"
    )
    addresses_pain_points: List[str] = Field(
        default_factory=list, description="Pain point IDs or summaries resolved by this option"
    )
    migration_outline: MigrationOutline
    documentation_urls: List[str] = Field(default_factory=list)


class PainPoint(BaseModel):
    """A bottleneck, vulnerability, or architectural issue surfaced by another agent."""
    id: Optional[str] = None
    source_agent: str = Field(
        description="Source agent reporting the problem (e.g. 'architecture_review', 'scale_load', 'security')"
    )
    category: str = Field(
        description="Type of issue (e.g. 'n_plus_one_query', 'high_coupling', 'cve', 'latency')"
    )
    severity: str = Field(default="medium")
    description: str
    affected_components: List[str] = Field(default_factory=list)


class StackMetadata(BaseModel):
    """Structured representation of the codebase's existing technology stack."""
    languages: List[str] = Field(default_factory=list)
    frameworks: List[str] = Field(default_factory=list)
    databases: List[str] = Field(default_factory=list)
    libraries: Dict[str, str] = Field(default_factory=dict)
    architecture_style: Optional[str] = None
    deployment_target: Optional[str] = None


class TechScoutInput(BaseModel):
    """Input payload accepted by the Tech Scout Agent."""
    stack_metadata: Union[Dict[str, Any], StackMetadata] = Field(
        default_factory=dict,
        description="Current technology stack metadata (languages, frameworks, DBs, dependencies)",
    )
    pain_points_from_other_agents: List[Union[str, Dict[str, Any], PainPoint]] = Field(
        default_factory=list,
        description="Collected pain points and bottlenecks from other agents",
    )
    focus_areas: Optional[List[str]] = Field(
        default=None,
        description="Optional list of specific technology domains to focus research on",
    )
    max_options: int = Field(
        default=5, ge=1, le=20, description="Maximum number of ranked options to produce"
    )


class TechScoutOutput(BaseModel):
    """Output payload produced by the Tech Scout Agent."""
    ranked_options_with_migration_outline: List[RankedOption] = Field(
        default_factory=list,
        description="Ranked technological alternatives with complete migration roadmaps",
    )
    total_options_researched: int = Field(default=0, ge=0)
    pain_points_addressed_count: int = Field(default=0, ge=0)
    top_recommendation: Optional[str] = Field(
        default=None, description="Title of the highest-ranked technological recommendation"
    )
    executive_summary: str = Field(default="", description="Executive research synthesis")
