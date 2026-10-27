"""
Agent 12: Scale & Load (Layer: Runtime).
Role: Capacity analyst.
Description: Finds N+1 queries, missing indexes and caching gaps, runs load tests, and estimates capacity.
Access: read-only
"""

from collections import defaultdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import time
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from agents.base import AgentMetadata, BaseAgent
from core.exceptions import UnauthorizedAccessError
from models.registry import NodeType, RegistryNode
from models.scale_load import (
    Bottleneck,
    BottleneckSeverity,
    BottleneckType,
    CapacityEstimate,
    CapacityStatus,
    HttpMetricSummary,
    LoadTestResult,
    ScaleLoadInput,
    ScaleLoadOutput,
    TrafficTarget,
)
from storage.registry_store import CodeRegistryStore
from tools.graph_traverse_tool import GraphTraverseTool
from tools.k6_tool import K6Tool
from tools.locust_tool import LocustTool
from tools.registry_lookup_tool import RegistryLookupTool


SCALE_LOAD_METADATA = AgentMetadata(
    id="scale_load",
    name="Scale & Load",
    layer="runtime",
    role="Capacity analyst",
    description="Finds N+1 queries, missing indexes and caching gaps, runs load tests, and estimates capacity.",
    access="read-only",
    model_tier="medium",
    inputs=[
        "graph_hot_paths",
        "query_logs",
        "k6_or_locust_scripts",
        "traffic_target",
    ],
    outputs=[
        "bottlenecks",
        "load_test_results",
        "capacity_estimate",
    ],
    tools=[
        "k6",
        "locust",
        "graph.traverse",
    ],
    trigger="on request and before release",
    optional=False,
)


class ScaleLoadAgent(BaseAgent):
    """
    Scale & Load Agent discovers N+1 queries, missing indexes, and caching gaps,
    executes or evaluates k6/Locust load tests, and estimates system throughput capacity.
    """

    def __init__(
        self,
        metadata: Optional[AgentMetadata] = None,
        registry_store: Optional[CodeRegistryStore] = None,
        repo_root: Optional[Union[str, Path]] = None,
        log_file: Optional[str] = None,
    ):
        meta = (metadata or SCALE_LOAD_METADATA).model_copy(deep=True)
        super().__init__(metadata=meta, log_file=log_file)
        self.registry_store = registry_store or CodeRegistryStore()
        self.repo_root = Path(repo_root) if repo_root else Path.cwd()

        # Tools
        self.graph_tool = GraphTraverseTool(self.registry_store)
        self.lookup_tool = RegistryLookupTool(store=self.registry_store)
        self.k6_tool = K6Tool()
        self.locust_tool = LocustTool()

    def execute(self, inputs: ScaleLoadInput) -> ScaleLoadOutput:
        """
        Executes capacity analysis, identifies bottlenecks, runs load tests,
        and projects capacity against target traffic SLAs.
        """
        # Strict read-only access enforcement
        self.require_access("read-only")

        t0 = self.log_started({
            "hot_paths_count": len(inputs.graph_hot_paths),
            "has_query_logs": bool(inputs.query_logs),
            "has_load_scripts": bool(inputs.k6_or_locust_scripts),
            "target_rps": (
                inputs.traffic_target.target_rps
                if isinstance(inputs.traffic_target, TrafficTarget)
                else inputs.traffic_target.get("target_rps", 100.0)
            ),
        })

        try:
            traffic_target = (
                inputs.traffic_target
                if isinstance(inputs.traffic_target, TrafficTarget)
                else TrafficTarget(**inputs.traffic_target)
            )

            # 1. Parse & Ingest Database Query Logs
            self.log_event(
                event="tool.query_logs",
                message="Parsing query execution logs and profiling SQL statement patterns",
            )
            parsed_queries = self._ingest_query_logs(inputs.query_logs)

            # 2. Tool 1: Graph Traversal for Hot Paths
            self.log_event(
                event="tool.graph_traverse",
                message="Traversing dependency graph downstream from critical hot paths",
                hot_paths_count=len(inputs.graph_hot_paths),
            )
            hot_path_details = self._analyze_hot_paths(inputs.graph_hot_paths)

            # 3. Detect N+1 Queries, Missing Indexes, Caching Gaps
            self.log_event(
                event="analysis.bottlenecks",
                message="Detecting N+1 queries, missing indexes, and un-cached hot paths",
                total_queries=len(parsed_queries),
            )
            bottlenecks = self._detect_bottlenecks(parsed_queries, hot_path_details)

            # 4. Tool 2 & 3: Run / Evaluate k6 and Locust Load Tests
            self.log_event(
                event="tool.load_tests",
                message="Executing or evaluating k6 and Locust load test scenarios",
            )
            load_test_results = self._run_or_eval_load_tests(
                inputs.k6_or_locust_scripts, traffic_target
            )

            # 5. Formulate Capacity Projections
            capacity_estimate = self._calculate_capacity_estimate(
                bottlenecks=bottlenecks,
                load_results=load_test_results,
                target=traffic_target,
            )

            # Summary narrative
            summary = self._generate_summary(bottlenecks, load_test_results, capacity_estimate)

            self.log_completed(
                start_time=t0,
                outputs_summary={
                    "bottlenecks_count": len(bottlenecks),
                    "load_tests_run": len(load_test_results),
                    "capacity_status": capacity_estimate.status.value,
                    "current_max_rps": capacity_estimate.current_max_rps,
                    "target_rps": capacity_estimate.target_rps,
                },
            )

            return ScaleLoadOutput(
                bottlenecks=bottlenecks,
                load_test_results=load_test_results,
                capacity_estimate=capacity_estimate,
                total_queries_analyzed=len(parsed_queries),
                hot_paths_evaluated=len(inputs.graph_hot_paths),
                summary=summary,
            )

        except Exception as e:
            self.log_failed(t0, e)
            raise

    # --------------------------------------------------------------------------
    # Subroutines: Query Log Ingestion & SQL Normalization
    # --------------------------------------------------------------------------

    def _ingest_query_logs(
        self, query_logs: Union[str, Path, List[Union[str, Dict[str, Any]]]]
    ) -> List[Dict[str, Any]]:
        """Parses various query log formats (files, dicts, SQL lines, or slow query logs)."""
        raw_entries: List[Union[str, Dict[str, Any]]] = []

        if isinstance(query_logs, (str, Path)):
            p = Path(query_logs)
            if p.is_file():
                try:
                    content = p.read_text(encoding="utf-8")
                    # Check if JSON
                    if content.strip().startswith(("{", "[")):
                        loaded = json.loads(content)
                        if isinstance(loaded, list):
                            raw_entries.extend(loaded)
                        elif isinstance(loaded, dict):
                            raw_entries.extend(loaded.get("queries", [loaded]))
                    else:
                        # Plain text SQL log
                        for line in content.splitlines():
                            if line.strip() and not line.strip().startswith("--"):
                                raw_entries.append(line.strip())
                except Exception:
                    pass
            else:
                raw_entries.append(str(query_logs))

        elif isinstance(query_logs, list):
            for item in query_logs:
                if isinstance(item, (str, Path)) and Path(item).is_file():
                    p = Path(item)
                    try:
                        content = p.read_text(encoding="utf-8")
                        if content.strip().startswith(("{", "[")):
                            loaded = json.loads(content)
                            if isinstance(loaded, list):
                                raw_entries.extend(loaded)
                            elif isinstance(loaded, dict):
                                raw_entries.extend(loaded.get("queries", [loaded]))
                        else:
                            for line in content.splitlines():
                                if line.strip() and not line.strip().startswith("--"):
                                    raw_entries.append(line.strip())
                    except Exception:
                        pass
                else:
                    raw_entries.append(item)

        parsed_list: List[Dict[str, Any]] = []
        for entry in raw_entries:
            parsed = self._parse_single_query_entry(entry)
            if parsed:
                parsed_list.append(parsed)

        return parsed_list

    def _parse_single_query_entry(self, entry: Union[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Normalizes a single query record into structured format."""
        if isinstance(entry, dict):
            sql = entry.get("sql", entry.get("query", entry.get("statement", "")))
            if not sql:
                return None
            dur_ms = float(entry.get("duration_ms", entry.get("duration", entry.get("latency_ms", 1.0))))
            return {
                "sql": sql,
                "normalized_sql": self._normalize_sql(sql),
                "duration_ms": dur_ms,
                "file_path": entry.get("file_path", entry.get("caller_file")),
                "line_number": entry.get("line_number", entry.get("caller_line")),
                "table_name": entry.get("table_name") or self._extract_table_from_sql(sql),
                "plan": entry.get("plan", entry.get("execution_plan")),
                "rows": int(entry.get("rows", entry.get("rows_examined", 1))),
                "request_id": entry.get("request_id", entry.get("trace_id")),
            }

        elif isinstance(entry, str):
            line = entry.strip()
            if not line:
                return None

            # Look for duration patterns: [12.5ms], (15.2 ms), duration: 45ms
            dur_ms = 2.0
            dur_match = re.search(r"(\d+(?:\.\d+)?)\s*ms", line, re.IGNORECASE)
            if dur_match:
                dur_ms = float(dur_match.group(1))

            # Look for file location: at /path/to/file.py:45
            loc_match = re.search(r"(?:at\s+|in\s+)?([a-zA-Z0-9_\-/\\]+\.(?:py|js|ts|java)):(\d+)", line)
            fpath = loc_match.group(1) if loc_match else None
            lineno = int(loc_match.group(2)) if loc_match else None

            # Strip log prefixes (e.g. 2026-10-27 22:00:00 [DEBUG] SQL: )
            sql_text = line
            sql_match = re.search(r"(?:SELECT|INSERT|UPDATE|DELETE|WITH)\s+.+", line, re.IGNORECASE)
            if sql_match:
                sql_text = sql_match.group(0)

            return {
                "sql": sql_text,
                "normalized_sql": self._normalize_sql(sql_text),
                "duration_ms": dur_ms,
                "file_path": fpath,
                "line_number": lineno,
                "table_name": self._extract_table_from_sql(sql_text),
                "plan": None,
                "rows": 1,
                "request_id": None,
            }

        return None

    def _normalize_sql(self, sql: str) -> str:
        """Parameterizes SQL literals to cluster identical query templates."""
        cleaned = sql.strip().rstrip(";")
        # Replace string literals
        cleaned = re.sub(r"'[^']*'", "?", cleaned)
        # Replace number literals in WHERE / VALUES / IN
        cleaned = re.sub(r"\b\d+\b", "?", cleaned)
        # Replace multi-parameter IN lists
        cleaned = re.sub(r"IN\s*\(\s*(?:\?\s*,\s*)*\?\s*\)", "IN (?)", cleaned, flags=re.IGNORECASE)
        # Collapse multiple spaces
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    def _extract_table_from_sql(self, sql: str) -> Optional[str]:
        """Extracts primary table name from SQL statement."""
        m = re.search(
            r"(?:FROM|UPDATE|INTO|JOIN)\s+([a-zA-Z0-9_]+)", sql, re.IGNORECASE
        )
        if m:
            tbl = m.group(1).lower()
            if tbl not in ("select", "where", "group", "order", "limit", "set", "values"):
                return tbl
        return None

    # --------------------------------------------------------------------------
    # Subroutines: Graph Traversal for Hot Paths
    # --------------------------------------------------------------------------

    def _analyze_hot_paths(self, hot_paths: List[Union[str, Dict[str, Any]]]) -> List[Dict[str, Any]]:
        """Traverses downstream graph from hot path roots to discover linked tables & services."""
        analyzed = []
        for hp in hot_paths:
            root_id = hp if isinstance(hp, str) else hp.get("node_id", hp.get("id", ""))
            if not root_id:
                continue

            # Lookup node in registry
            node = self.lookup_tool.get(root_id)
            if not node:
                # Try finding API by endpoint route
                for n in self.registry_store.list_all():
                    if n.type == NodeType.API and n.location.endpoint_route == root_id:
                        node = n
                        break

            downstream_tables: Set[str] = set()
            downstream_apis: Set[str] = set()
            max_depth = 0

            if node:
                # Traverse downstream graph
                traversal = self.graph_tool.traverse(
                    start_node_ids=[node.id],
                    direction="downstream",
                    max_depth=4,
                )
                max_depth = traversal.max_depth_reached
                for nid in traversal.downstream_node_ids:
                    dn = self.lookup_tool.get(nid)
                    if dn:
                        if dn.type == NodeType.TABLE:
                            downstream_tables.add(dn.name)
                        elif dn.type == NodeType.API:
                            downstream_apis.add(dn.name)

            analyzed.append({
                "root_id": root_id,
                "node": node,
                "downstream_tables": sorted(list(downstream_tables)),
                "downstream_apis": sorted(list(downstream_apis)),
                "max_depth": max_depth,
            })

        return analyzed

    # --------------------------------------------------------------------------
    # Subroutines: Bottleneck Detection Logic
    # --------------------------------------------------------------------------

    def _detect_bottlenecks(
        self,
        queries: List[Dict[str, Any]],
        hot_paths: List[Dict[str, Any]],
    ) -> List[Bottleneck]:
        """Detects N+1 queries, missing indexes, caching gaps, and slow queries."""
        bottlenecks: List[Bottleneck] = []

        # Group queries by normalized SQL template
        grouped_templates: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for q in queries:
            grouped_templates[q["normalized_sql"]].append(q)

        # 1. Detect N+1 Queries
        for template, execs in grouped_templates.items():
            count = len(execs)
            # Threshold: identical template executed >= 3 times
            if count >= 3:
                # Check if it has a foreign key or ID parameter filter
                is_fk_filter = any(
                    k in template.lower() for k in ("where", "_id", "id =", "id in", "user_id", "order_id")
                )
                if is_fk_filter or count >= 5:
                    total_dur = sum(e["duration_ms"] for e in execs)
                    avg_dur = total_dur / count
                    sample = execs[0]
                    tbl = sample["table_name"] or "database"

                    # Calculate severity based on count and latency
                    if count >= 20 or total_dur >= 500.0:
                        sev = BottleneckSeverity.CRITICAL
                    elif count >= 8 or total_dur >= 200.0:
                        sev = BottleneckSeverity.HIGH
                    else:
                        sev = BottleneckSeverity.MEDIUM

                    linked_node, fpath, lineno = self._resolve_code_location(sample, tbl)

                    btnk = Bottleneck(
                        type=BottleneckType.N_PLUS_ONE_QUERY,
                        severity=sev,
                        title=f"N+1 Query loop detected on '{tbl}' ({count}x iterations)",
                        description=(
                            f"Identical parameterized query executed {count} times, incurring "
                            f"{total_dur:.1f}ms total latency (avg: {avg_dur:.1f}ms per query). "
                            f"Indicates looped ORM fetch instead of batch/eager loading."
                        ),
                        linked_node_id=linked_node.id if linked_node else None,
                        file_path=fpath or (linked_node.location.path if linked_node else None),
                        line_number=lineno or (linked_node.location.start_line if linked_node else None),
                        table_name=tbl,
                        query_pattern=template,
                        execution_count=count,
                        avg_latency_ms=round(avg_dur, 2),
                        total_time_ms=round(total_dur, 2),
                        evidence=[
                            f"Normalized Template: {template}",
                            f"Iteration count: {count} queries in burst",
                            f"Wasted roundtrip latency: ~{(count - 1) * avg_dur:.1f}ms",
                        ],
                        remediation=(
                            f"Replace iterative single-row lookups on '{tbl}' with bulk retrieval "
                            f"(e.g. 'WHERE id IN (?)') or ORM eager loading ('select_related' / 'prefetch_related')."
                        ),
                    )
                    bottlenecks.append(btnk)

        # 2. Detect Missing Indexes
        for template, execs in grouped_templates.items():
            sample = execs[0]
            plan = sample.get("plan") or ""
            dur = sum(e["duration_ms"] for e in execs) / len(execs)
            tbl = sample["table_name"]

            has_seq_scan = "seq scan" in plan.lower() or "table scan" in plan.lower()
            # If query filters by column and duration is slow, or plan indicates full table scan
            if tbl and (has_seq_scan or dur > 80.0):
                # Extract filtered columns: WHERE col1 = ? AND col2 = ?
                where_match = re.search(r"WHERE\s+([^;]+)", sample["sql"], re.IGNORECASE)
                cols: List[str] = []
                if where_match:
                    where_clause = where_match.group(1)
                    col_matches = re.findall(r"([a-zA-Z0-9_]+)\s*(?:=|IN|LIKE|<|>)", where_clause)
                    cols = [c for c in col_matches if c.lower() not in ("and", "or", "not")]

                if cols or has_seq_scan:
                    primary_col = cols[0] if cols else "id"
                    idx_name = f"idx_{tbl}_{primary_col}"
                    create_idx_sql = f"CREATE INDEX {idx_name} ON {tbl} ({primary_col});"

                    sev = BottleneckSeverity.HIGH if dur > 200.0 else BottleneckSeverity.MEDIUM
                    linked_node, fpath, lineno = self._resolve_code_location(sample, tbl)

                    btnk = Bottleneck(
                        type=BottleneckType.MISSING_INDEX,
                        severity=sev,
                        title=f"Missing index on '{tbl}' for column '{primary_col}' ({dur:.1f}ms)",
                        description=(
                            f"Query on table '{tbl}' performs full table scan or unindexed lookup "
                            f"filtering on '{primary_col}'. Average latency: {dur:.1f}ms."
                        ),
                        linked_node_id=linked_node.id if linked_node else None,
                        file_path=fpath or (linked_node.location.path if linked_node else None),
                        line_number=lineno or (linked_node.location.start_line if linked_node else None),
                        table_name=tbl,
                        query_pattern=template,
                        execution_count=len(execs),
                        avg_latency_ms=round(dur, 2),
                        total_time_ms=round(sum(e["duration_ms"] for e in execs), 2),
                        evidence=[
                            f"Plan: {plan or 'Full scan indicated by query latency'}",
                            f"Recommended DDL: {create_idx_sql}",
                        ],
                        remediation=f"Add database index: `{create_idx_sql}`",
                    )
                    bottlenecks.append(btnk)

        # 3. Detect Caching Gaps on Read-Heavy Templates & Hot Paths
        for template, execs in grouped_templates.items():
            count = len(execs)
            # If query is a pure SELECT with high frequency (>= 5x)
            if template.upper().startswith("SELECT") and count >= 5:
                total_dur = sum(e["duration_ms"] for e in execs)
                tbl = execs[0]["table_name"] or "entity"

                linked_node, fpath, lineno = self._resolve_code_location(execs[0], tbl)
                cache_key_example = f"cache:{tbl}:" + "{id}"

                btnk = Bottleneck(
                    type=BottleneckType.CACHING_GAP,
                    severity=BottleneckSeverity.MEDIUM if total_dur < 500.0 else BottleneckSeverity.HIGH,
                    title=f"Caching gap on high-frequency read for '{tbl}' ({count} hits)",
                    description=(
                        f"Read-heavy SELECT on '{tbl}' called {count} times without intermediate "
                        f"caching tier, generating repetitive database load."
                    ),
                    linked_node_id=linked_node.id if linked_node else None,
                    file_path=fpath or (linked_node.location.path if linked_node else None),
                    line_number=lineno or (linked_node.location.start_line if linked_node else None),
                    table_name=tbl,
                    query_pattern=template,
                    execution_count=count,
                    avg_latency_ms=round(total_dur / count, 2),
                    total_time_ms=round(total_dur, 2),
                    evidence=[
                        f"Repetitive SELECT count: {count}",
                        f"Potential cache key: `{cache_key_example}`",
                        f"Estimated DB load reduction: ~{max(80, int((count - 1) / count * 100))}%",
                    ],
                    remediation=(
                        f"Implement Redis Cache-Aside or application in-memory LRU caching with key "
                        f"`{cache_key_example}` and TTL (e.g. 300s)."
                    ),
                )
                bottlenecks.append(btnk)

        # 4. Check Hot Paths for Un-cached Deep Traversals
        for hp in hot_paths:
            node = hp.get("node")
            root_id = hp.get("root_id")
            tables = hp.get("downstream_tables", [])
            max_depth = hp.get("max_depth", 0)

            if max_depth >= 3 or len(tables) >= 3:
                # Deep multi-table dependency chain
                bottlenecks.append(
                    Bottleneck(
                        type=BottleneckType.HIGH_LATENCY_HOT_PATH,
                        severity=BottleneckSeverity.MEDIUM,
                        title=f"Complex dependency chain on hot path '{root_id}' ({len(tables)} tables)",
                        description=(
                            f"Hot path reaches {len(tables)} database tables across depth {max_depth}. "
                            f"High fan-out increases latency variance under concurrent traffic."
                        ),
                        linked_node_id=node.id if node else None,
                        file_path=node.location.path if node else None,
                        line_number=node.location.start_line if node else None,
                        evidence=[
                            f"Downstream tables: {', '.join(tables) or 'none'}",
                            f"Graph traversal depth: {max_depth}",
                        ],
                        remediation="Denormalize read models or introduce response caching at API gateway boundary.",
                    )
                )

        # Sort bottlenecks by severity then total time
        sev_weights = {
            BottleneckSeverity.CRITICAL: 0,
            BottleneckSeverity.HIGH: 1,
            BottleneckSeverity.MEDIUM: 2,
            BottleneckSeverity.LOW: 3,
            BottleneckSeverity.INFO: 4,
        }
        bottlenecks.sort(key=lambda b: (sev_weights.get(b.severity, 5), -b.total_time_ms))
        return bottlenecks

    def _resolve_code_location(
        self, query_dict: Dict[str, Any], table_name: Optional[str]
    ) -> Tuple[Optional[RegistryNode], Optional[str], Optional[int]]:
        """Resolves file path, line number, and canonical RegistryNode for a query."""
        fpath = query_dict.get("file_path")
        lineno = query_dict.get("line_number")

        if fpath:
            nodes = self.lookup_tool.get_by_path(fpath)
            if lineno and nodes:
                for n in nodes:
                    if (
                        n.type in (NodeType.FUNCTION, NodeType.CLASS, NodeType.API)
                        and n.location.start_line is not None
                        and n.location.start_line <= lineno <= (n.location.end_line or lineno)
                    ):
                        return n, fpath, lineno
                return nodes[0], fpath, lineno

        # Try looking up table node in registry
        if table_name:
            for n in self.registry_store.list_all():
                if n.type == NodeType.TABLE and n.name.lower() == table_name.lower():
                    return n, n.location.path, n.location.start_line

        return None, fpath, lineno

    # --------------------------------------------------------------------------
    # Subroutines: Load Test Execution & Evaluation
    # --------------------------------------------------------------------------

    def _run_or_eval_load_tests(
        self,
        scripts: Union[str, Path, List[Union[str, Path, Dict[str, Any]]]],
        target: TrafficTarget,
    ) -> List[LoadTestResult]:
        """Runs or simulates k6 and Locust load tests."""
        results: List[LoadTestResult] = []
        script_items: List[Union[str, Path, Dict[str, Any]]] = []

        if isinstance(scripts, (str, Path, dict)):
            script_items = [scripts]
        elif isinstance(scripts, list):
            script_items = list(scripts)

        # If no explicit load script was provided, run default synthetic load profile
        if not script_items:
            k6_default = self.k6_tool.execute_or_eval(
                script_or_path="",
                vus=target.peak_concurrent_users or max(int(target.target_rps * 0.1), 10),
                duration_seconds=target.test_duration_seconds,
            )
            results.append(k6_default)
            return results

        for item in script_items:
            # Determine engine: k6 or locust
            is_k6 = False
            is_locust = False

            if isinstance(item, dict):
                engine = str(item.get("engine", "")).lower()
                is_k6 = engine == "k6"
                is_locust = engine == "locust"

            elif isinstance(item, (str, Path)):
                s_str = str(item).lower()
                if "k6" in s_str or s_str.endswith(".js"):
                    is_k6 = True
                elif "locust" in s_str or s_str.endswith(".py") or "stats.csv" in s_str:
                    is_locust = True

            # Default to k6 if unspecified
            if is_locust:
                res = self.locust_tool.execute_or_eval(
                    script_or_path=item,
                    users=target.peak_concurrent_users or max(int(target.target_rps * 0.1), 10),
                    duration_seconds=target.test_duration_seconds,
                )
                results.append(res)
            else:
                res = self.k6_tool.execute_or_eval(
                    script_or_path=item,
                    vus=target.peak_concurrent_users or max(int(target.target_rps * 0.1), 10),
                    duration_seconds=target.test_duration_seconds,
                )
                results.append(res)

        return results

    # --------------------------------------------------------------------------
    # Subroutines: Capacity Projection & Scaling Analysis
    # --------------------------------------------------------------------------

    def _calculate_capacity_estimate(
        self,
        bottlenecks: List[Bottleneck],
        load_results: List[LoadTestResult],
        target: TrafficTarget,
    ) -> CapacityEstimate:
        """Calculates current max throughput, bottlenecks impact, and scaling needs."""
        # 1. Base latency derivation from load tests and bottlenecks
        measured_rps = 0.0
        measured_p95 = 50.0

        if load_results:
            best_load = max(load_results, key=lambda lr: lr.metrics.rps)
            measured_rps = best_load.metrics.rps
            measured_p95 = best_load.metrics.latency_p95_ms or 50.0

        # Compute delay caused by critical and high bottlenecks
        wasted_bottleneck_latency_ms = sum(
            b.total_time_ms / max(b.execution_count, 1)
            for b in bottlenecks
            if b.severity in (BottleneckSeverity.CRITICAL, BottleneckSeverity.HIGH)
        )

        effective_p95_ms = max(measured_p95, 20.0) + (wasted_bottleneck_latency_ms * 0.5)

        # Typical web app concurrent thread/worker pool per instance: 20 workers
        workers_per_instance = 20
        # Little's Law: Capacity RPS = Concurrency / Latency(s)
        single_instance_max_rps = max(
            round(workers_per_instance / (effective_p95_ms / 1000.0), 1),
            5.0,
        )

        # If load test directly measured higher RPS, use that as lower bound
        current_max_rps = max(single_instance_max_rps, measured_rps)

        # Gap relative to target
        target_rps = target.target_rps
        gap_pct = round(((current_max_rps - target_rps) / target_rps) * 100.0, 1)

        # Capacity status assessment
        if current_max_rps >= target_rps * 1.15:
            status = CapacityStatus.CAPACITY_SUFFICIENT
        elif current_max_rps >= target_rps * 0.85:
            status = CapacityStatus.CAPACITY_MARGINAL
        else:
            status = CapacityStatus.CAPACITY_DEFICIT

        # Scaling instances needed
        instances_needed = max(1, math.ceil(target_rps / single_instance_max_rps))

        # Identify primary limiting factor
        if bottlenecks:
            primary_btnk = bottlenecks[0]
            limiting_factor = f"{primary_btnk.title} ({primary_btnk.avg_latency_ms}ms)"
        else:
            limiting_factor = "Compute worker concurrency and network I/O"

        # Caching strategy impact
        has_caching_gap = any(b.type == BottleneckType.CACHING_GAP for b in bottlenecks)
        caching_multiplier = 3.5 if has_caching_gap else 1.5
        cache_strat = (
            "Redis Cache-Aside with 300s TTL on high-frequency read endpoints"
            if has_caching_gap
            else "In-memory LRU application cache"
        )

        # Collect recommended index DDL statements
        recommended_indexes: List[str] = []
        for b in bottlenecks:
            if b.type == BottleneckType.MISSING_INDEX:
                for ev in b.evidence:
                    if "CREATE INDEX" in ev:
                        idx_stmt = re.search(r"CREATE INDEX [^;]+;", ev)
                        if idx_stmt and idx_stmt.group(0) not in recommended_indexes:
                            recommended_indexes.append(idx_stmt.group(0))

        headroom_ratio = round(current_max_rps / target_rps, 2)

        return CapacityEstimate(
            status=status,
            current_max_rps=round(current_max_rps, 1),
            target_rps=target_rps,
            target_concurrent_users=target.peak_concurrent_users,
            capacity_gap_pct=gap_pct,
            estimated_required_instances=instances_needed,
            limiting_factor=limiting_factor,
            recommended_cache_strategy=cache_strat,
            caching_throughput_multiplier=caching_multiplier,
            recommended_indexes=recommended_indexes,
            headroom_multiplier=headroom_ratio,
        )

    def _generate_summary(
        self,
        bottlenecks: List[Bottleneck],
        load_tests: List[LoadTestResult],
        capacity: CapacityEstimate,
    ) -> str:
        """Builds an executive summary of capacity analysis and load findings."""
        n1_count = sum(1 for b in bottlenecks if b.type == BottleneckType.N_PLUS_ONE_QUERY)
        idx_count = sum(1 for b in bottlenecks if b.type == BottleneckType.MISSING_INDEX)
        cache_count = sum(1 for b in bottlenecks if b.type == BottleneckType.CACHING_GAP)

        status_emoji = "🟢" if capacity.status == CapacityStatus.CAPACITY_SUFFICIENT else (
            "🟡" if capacity.status == CapacityStatus.CAPACITY_MARGINAL else "🔴"
        )

        return (
            f"Capacity Analysis Status: {status_emoji} {capacity.status.value}. "
            f"Estimated max throughput is {capacity.current_max_rps:.1f} RPS against target {capacity.target_rps:.1f} RPS "
            f"(headroom: {capacity.headroom_multiplier}x, gap: {capacity.capacity_gap_pct:+.1f}%). "
            f"Identified {len(bottlenecks)} bottlenecks ({n1_count} N+1 query loops, {idx_count} missing indexes, "
            f"{cache_count} caching gaps). Primary constraint: '{capacity.limiting_factor}'. "
            f"Estimated required horizontal scale: {capacity.estimated_required_instances} instance(s)."
        )
