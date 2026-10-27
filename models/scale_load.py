"""
Data models for Agent 12: Scale & Load (Layer: Runtime).
Role: Capacity analyst.
Description: Finds N+1 queries, missing indexes and caching gaps, runs load tests, and estimates capacity.
Access: read-only
"""

from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import uuid

from pydantic import BaseModel, Field


class BottleneckType(str, Enum):
    """Types of capacity, database, and concurrency bottlenecks."""
    N_PLUS_ONE_QUERY = "n_plus_one_query"
    MISSING_INDEX = "missing_index"
    CACHING_GAP = "caching_gap"
    SLOW_QUERY = "slow_query"
    HIGH_LATENCY_HOT_PATH = "high_latency_hot_path"
    CONNECTION_POOL_CONTENTION = "connection_pool_contention"
    UNBOUNDED_RESULT_SET = "unbounded_result_set"


class BottleneckSeverity(str, Enum):
    """Severity ratings for detected bottlenecks."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class Bottleneck(BaseModel):
    """Detailed bottleneck pinpointed in code, database queries, or hot paths."""
    id: str = Field(default_factory=lambda: f"btnk_{uuid.uuid4().hex[:8]}")
    type: BottleneckType
    severity: BottleneckSeverity
    title: str
    description: str
    linked_node_id: Optional[str] = Field(
        default=None, description="Registry node ID (e.g. api:, function:, table:)"
    )
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    table_name: Optional[str] = None
    endpoint_route: Optional[str] = None
    query_pattern: Optional[str] = None
    execution_count: int = Field(default=1, ge=1)
    avg_latency_ms: float = Field(default=0.0, ge=0.0)
    total_time_ms: float = Field(default=0.0, ge=0.0)
    evidence: List[str] = Field(
        default_factory=list, description="Corroborating SQL patterns, stack frames, or hot paths"
    )
    remediation: str = Field(
        description="Actionable fix: eager loading, CREATE INDEX, caching layer, or batching"
    )


class HttpMetricSummary(BaseModel):
    """Summary of HTTP performance metrics from a load test run."""
    requests_total: int = Field(default=0, ge=0)
    requests_failed: int = Field(default=0, ge=0)
    error_rate_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    rps: float = Field(default=0.0, ge=0.0, description="Requests per second achieved")
    latency_p50_ms: float = Field(default=0.0, ge=0.0)
    latency_p90_ms: float = Field(default=0.0, ge=0.0)
    latency_p95_ms: float = Field(default=0.0, ge=0.0)
    latency_p99_ms: float = Field(default=0.0, ge=0.0)
    latency_min_ms: float = Field(default=0.0, ge=0.0)
    latency_max_ms: float = Field(default=0.0, ge=0.0)
    latency_avg_ms: float = Field(default=0.0, ge=0.0)


class LoadTestResult(BaseModel):
    """Aggregated outcome of executing or simulating a load test script."""
    engine: str = Field(description="Engine name: 'k6' or 'locust'")
    script_source: Optional[str] = Field(default=None, description="File path or snippet name")
    vus_or_users: int = Field(default=1, ge=1, description="Peak concurrent virtual users / clients")
    duration_seconds: float = Field(default=0.0, ge=0.0)
    metrics: HttpMetricSummary = Field(default_factory=HttpMetricSummary)
    checks_passed: int = Field(default=0, ge=0)
    checks_failed: int = Field(default=0, ge=0)
    thresholds_passed: bool = Field(default=True)
    failed_thresholds: List[str] = Field(default_factory=list)
    raw_output_summary: Optional[Dict[str, Any]] = None


class CapacityStatus(str, Enum):
    """Overall capacity assessment against target SLA."""
    CAPACITY_SUFFICIENT = "CAPACITY_SUFFICIENT"
    CAPACITY_MARGINAL = "CAPACITY_MARGINAL"
    CAPACITY_DEFICIT = "CAPACITY_DEFICIT"


class CapacityEstimate(BaseModel):
    """Calculated capacity headroom, bottlenecks, and instance scaling requirements."""
    status: CapacityStatus
    current_max_rps: float = Field(
        description="Estimated maximum sustainable throughput in requests per second"
    )
    target_rps: float = Field(description="Desired target requests per second")
    target_concurrent_users: Optional[int] = None
    capacity_gap_pct: float = Field(
        description="Surplus percentage (+) or deficit percentage (-) relative to target RPS"
    )
    estimated_required_instances: int = Field(
        default=1, ge=1, description="Estimated server instances required to meet target RPS"
    )
    limiting_factor: str = Field(
        description="Primary factor or bottleneck constraining current capacity"
    )
    recommended_cache_strategy: Optional[str] = Field(
        default=None, description="Recommended caching approach (e.g. Redis Cache-Aside, LRU)"
    )
    caching_throughput_multiplier: float = Field(
        default=1.0, ge=1.0, description="Estimated throughput multiplier achievable with caching"
    )
    recommended_indexes: List[str] = Field(
        default_factory=list, description="SQL statements for recommended indexes"
    )
    headroom_multiplier: float = Field(
        default=1.0, description="Ratio of current max RPS to target RPS"
    )


class TrafficTarget(BaseModel):
    """Traffic and concurrency target specifications."""
    target_rps: float = Field(default=100.0, ge=1.0, description="Target throughput in RPS")
    peak_concurrent_users: Optional[int] = Field(default=None, ge=1)
    target_p99_latency_ms: float = Field(
        default=200.0, ge=1.0, description="Maximum permissible p99 latency in milliseconds"
    )
    test_duration_seconds: float = Field(default=30.0, ge=1.0)
    ramp_up_seconds: float = Field(default=5.0, ge=0.0)


class ScaleLoadInput(BaseModel):
    """Input payload accepted by the Scale & Load Agent."""
    graph_hot_paths: List[Union[str, Dict[str, Any]]] = Field(
        default_factory=list,
        description="High-frequency code/system nodes, routes, or transaction paths in the graph",
    )
    query_logs: Union[str, Path, List[Union[str, Dict[str, Any]]]] = Field(
        default_factory=list,
        description="Database slow query logs, ORM statement traces, or execution log records",
    )
    k6_or_locust_scripts: Union[str, Path, List[Union[str, Path, Dict[str, Any]]]] = Field(
        default_factory=list,
        description="k6 JavaScript scripts or Locust Python scenario files or configs",
    )
    traffic_target: Union[Dict[str, Any], TrafficTarget] = Field(
        default_factory=TrafficTarget,
        description="Target traffic requirements (target_rps, peak_concurrent_users, p99 SLA)",
    )


class ScaleLoadOutput(BaseModel):
    """Output payload produced by the Scale & Load Agent."""
    bottlenecks: List[Bottleneck] = Field(
        default_factory=list,
        description="Pinpointed N+1 queries, missing indexes, caching gaps, and hot paths",
    )
    load_test_results: List[LoadTestResult] = Field(
        default_factory=list,
        description="Outcomes and HTTP latency distributions from k6 and Locust load tests",
    )
    capacity_estimate: CapacityEstimate = Field(
        description="Capacity projection, max sustainable RPS, and horizontal scaling estimates",
    )
    total_queries_analyzed: int = Field(default=0, ge=0)
    hot_paths_evaluated: int = Field(default=0, ge=0)
    summary: str = Field(default="", description="Executive capacity and load summary")
