"""
HTTP API server and static asset host for the Multi-Agent Visual Dashboard.
Zero-dependency, multi-threaded REST API interfacing directly with CodeRegistryStore,
OrchestratorAgent, ResultAggregatorCriticAgent, and AgentLogger.
"""

from collections import defaultdict
import http.server
import json
import mimetypes
import os
from pathlib import Path
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from agents import (
    ARCHITECTURE_REVIEW_METADATA,
    CODE_QUALITY_METADATA,
    COMPANY_RULES_METADATA,
    COST_TOKEN_GOVERNOR_METADATA,
    CRITIC_METADATA,
    DATA_SERVICE_MAPPER_METADATA,
    IMPACT_ANALYZER_METADATA,
    OBSERVABILITY_METADATA,
    ORCHESTRATOR_METADATA,
    REGISTRY_KEEPER_METADATA,
    RELATIONSHIP_LINKER_METADATA,
    SCALE_LOAD_METADATA,
    SECURITY_METADATA,
    STRUCTURE_MAPPER_METADATA,
    TECH_SCOUT_METADATA,
    TEST_GENERATION_METADATA,
)
from agents.control.orchestrator import OrchestratorAgent
from agents.graph.data_service_mapper import DataServiceMapper
from agents.graph.registry_keeper import RegistryKeeper
from agents.graph.relationship_linker import RelationshipLinker
from agents.graph.structure_mapper import StructureMapper
from core.logger import AgentLogger, agent_logger
from models.control import TaskExecutionMode, TaskPlanRequest
from models.registry import NodeType
from storage.registry_store import CodeRegistryStore


ALL_METADATA = [
    ORCHESTRATOR_METADATA,
    CRITIC_METADATA,
    REGISTRY_KEEPER_METADATA,
    STRUCTURE_MAPPER_METADATA,
    RELATIONSHIP_LINKER_METADATA,
    DATA_SERVICE_MAPPER_METADATA,
    IMPACT_ANALYZER_METADATA,
    ARCHITECTURE_REVIEW_METADATA,
    CODE_QUALITY_METADATA,
    SECURITY_METADATA,
    COMPANY_RULES_METADATA,
    OBSERVABILITY_METADATA,
    SCALE_LOAD_METADATA,
    TECH_SCOUT_METADATA,
    TEST_GENERATION_METADATA,
    COST_TOKEN_GOVERNOR_METADATA,
]


class MultiAgentUIServer:
    """Manages application state and execution lifecycle for the dashboard."""

    def __init__(
        self,
        repo_root: Optional[str] = ".",
        storage_path: Optional[str] = None,
        port: int = 8080,
        host: str = "127.0.0.1",
    ):
        self.port = port
        self.host = host
        self.store = CodeRegistryStore(persistence_path=storage_path)
        self.static_dir = Path(__file__).parent / "static"
        self._lock = threading.Lock()
        self.latest_output: Optional[Dict[str, Any]] = None
        self.approval_decisions: Dict[str, Dict[str, Any]] = {}
        self.httpd: Optional[http.server.ThreadingHTTPServer] = None

        if repo_root and str(repo_root).strip().lower() not in ("none", "", "blank"):
            self.repo_root: Optional[Path] = Path(repo_root).resolve()
            self.orchestrator: Optional[OrchestratorAgent] = OrchestratorAgent(registry_store=self.store, repo_root=str(self.repo_root))
            self._load_cached_report()
        else:
            self.repo_root = None
            self.orchestrator = None

    def _load_cached_report(self) -> None:
        """Attempt to restore the latest generated report from disk cache."""
        if not self.repo_root:
            return
        cache_file = self.repo_root / ".registry" / "latest_report.json"
        if cache_file.exists():
            try:
                data = json.loads(cache_file.read_text(encoding="utf-8"))
                self.latest_output = data
            except Exception as e:
                agent_logger.warning("control", "ui_server", "report.cache_load_failed", str(e))

    def _save_cached_report(self, data: Dict[str, Any]) -> None:
        """Persist latest orchestration run to disk cache."""
        if not self.repo_root:
            return
        cache_file = self.repo_root / ".registry" / "latest_report.json"
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            agent_logger.warning("control", "ui_server", "report.cache_save_failed", str(e))

    def get_status_payload(self) -> Dict[str, Any]:
        """Compile high-level dashboard status summary."""
        all_nodes = self.store.list_all(include_deleted=False)
        type_counts: Dict[str, int] = defaultdict(int)
        for n in all_nodes:
            type_counts[n.type.value] += 1

        agents_data = []
        for m in ALL_METADATA:
            agents_data.append({
                "id": m.id,
                "name": m.name,
                "layer": m.layer,
                "role": m.role,
                "description": m.description,
                "access": m.access,
                "model_tier": m.model_tier,
                "optional": m.optional,
            })

        latest_summary = None
        if self.latest_output and "unified_report" in self.latest_output:
            rep = self.latest_output["unified_report"]
            latest_summary = {
                "overall_health_score": rep.get("overall_health_score", 100.0),
                "active_findings_count": rep.get("active_findings_count", 0),
                "false_alarms_pruned": rep.get("false_alarms_pruned", 0),
                "critical_count": rep.get("critical_count", 0),
                "high_count": rep.get("high_count", 0),
                "medium_count": rep.get("medium_count", 0),
                "total_duration_ms": self.latest_output.get("total_duration_ms", 0.0),
                "status": self.latest_output.get("status", "COMPLETED"),
            }

        return {
            "status": "online",
            "repo_name": self.repo_root.name if self.repo_root else None,
            "repo_root": str(self.repo_root) if self.repo_root else None,
            "is_blank": self.repo_root is None,
            "storage_path": str(self.store.persistence_path or ":memory:"),
            "total_nodes": len(all_nodes),
            "type_counts": dict(type_counts),
            "total_agents": len(ALL_METADATA),
            "agents": agents_data,
            "latest_run": latest_summary,
            "timestamp": time.time(),
        }

    def get_graph_payload(self, node_limit: int = 500, filter_type: Optional[str] = None) -> Dict[str, Any]:
        """
        Extract visual graph representation with nodes and relational edges.
        Formatted specifically for interactive canvas force-directed graph.
        """
        all_nodes = self.store.list_all(include_deleted=False)

        if filter_type:
            types = set(filter_type.split(","))
            all_nodes = [n for n in all_nodes if n.type.value in types]

        # Prioritize Files, APIs, Tables, Services, then Functions/Classes up to limit
        priority = {
            NodeType.API: 1,
            NodeType.TABLE: 1,
            NodeType.SERVICE: 1,
            NodeType.FILE: 2,
            NodeType.CLASS: 3,
            NodeType.FUNCTION: 4,
            NodeType.MODULE: 5,
        }
        all_nodes.sort(key=lambda n: (priority.get(n.type, 10), n.name))
        selected_nodes = all_nodes[:node_limit]
        node_id_set = {n.id for n in selected_nodes}

        nodes_list = []
        file_to_nodes: Dict[str, List[str]] = defaultdict(list)

        for n in selected_nodes:
            # Layer association heuristic based on location path
            path = (n.location.path or "").lower()
            if "agent" in path:
                if "graph" in path:
                    layer = "graph"
                elif "understanding" in path:
                    layer = "understanding"
                elif "quality" in path:
                    layer = "quality"
                elif "safety" in path:
                    layer = "safety"
                elif "runtime" in path:
                    layer = "runtime"
                elif "control" in path:
                    layer = "control"
                elif "optional" in path:
                    layer = "optional"
                else:
                    layer = "action"
            elif "model" in path:
                layer = "models"
            elif "tool" in path:
                layer = "tools"
            elif "storage" in path:
                layer = "storage"
            elif "test" in path:
                layer = "tests"
            elif n.type in (NodeType.API, NodeType.TABLE, NodeType.SERVICE):
                layer = "architecture"
            else:
                layer = "core"

            val = 14 if n.type == NodeType.FILE else (18 if n.type in (NodeType.API, NodeType.TABLE) else 8)

            nodes_list.append({
                "id": n.id,
                "label": n.name,
                "type": n.type.value,
                "layer": layer,
                "path": n.location.path,
                "line": n.location.start_line,
                "val": val,
                "hash": n.hash[:8] if n.hash else "",
                "status": n.status.value,
            })

            if n.location.path:
                file_to_nodes[n.location.path].append(n.id)

        # Generate rich hierarchy & relational edges connecting modules, files, classes, functions, APIs, tables
        edges_list = []
        edge_set = set()

        def add_edge(src: str, tgt: str, rel_type: str, color: str):
            if src in node_id_set and tgt in node_id_set and src != tgt:
                edge_key = f"{src}->{tgt}:{rel_type}"
                if edge_key not in edge_set:
                    edge_set.add(edge_key)
                    edges_list.append({
                        "source": src,
                        "target": tgt,
                        "type": rel_type,
                        "color": color,
                    })

        # Map file paths to canonical file node IDs
        path_to_file_id: Dict[str, str] = {}
        for n in selected_nodes:
            if n.type == NodeType.FILE:
                clean_p = (n.location.path or "").strip("./")
                if clean_p:
                    path_to_file_id[clean_p] = n.id
                path_to_file_id[n.id] = n.id

        # 1. Connect File -> contained entities (Classes, Functions, Modules)
        for path, nids in file_to_nodes.items():
            clean_p = path.strip("./")
            file_id = path_to_file_id.get(clean_p) or f"file:{clean_p}"
            for child_id in nids:
                if child_id != file_id:
                    add_edge(file_id, child_id, "contains", "#00f0ff")

        # 2. Connect APIs and DB Tables to their source files & handler functions
        for n in selected_nodes:
            if n.type in (NodeType.API, NodeType.TABLE) and n.location.path:
                clean_p = n.location.path.strip("./")
                file_id = path_to_file_id.get(clean_p) or f"file:{clean_p}"
                edge_color = "#10b981" if n.type == NodeType.API else "#3b82f6"
                add_edge(n.id, file_id, "defines", edge_color)

                # Connect APIs to matching functions in the same file
                if n.type == NodeType.API:
                    for sibling_id in file_to_nodes.get(n.location.path, []):
                        if sibling_id.startswith("func:") or "function" in sibling_id:
                            add_edge(n.id, sibling_id, "routes_to", "#10b981")

                # Connect Tables to queries and sibling entities
                if n.type == NodeType.TABLE:
                    for sibling_id in file_to_nodes.get(n.location.path, []):
                        if sibling_id != n.id and (sibling_id.startswith("class:") or sibling_id.startswith("func:")):
                            add_edge(sibling_id, n.id, "queries", "#3b82f6")

        # 3. Connect Classes to contained methods & functions
        classes_in_graph = [n for n in selected_nodes if n.type == NodeType.CLASS]
        functions_in_graph = [n for n in selected_nodes if n.type == NodeType.FUNCTION]
        for c in classes_in_graph:
            for f in functions_in_graph:
                if f.location.path == c.location.path:
                    # If function signature or ID indicates it belongs to class
                    if c.name.lower() in f.id.lower() or (c.location.start_line and f.location.start_line and c.location.start_line <= f.location.start_line <= (c.location.end_line or 999999)):
                        add_edge(c.id, f.id, "defines", "#a855f7")

        # 4. Connect intra-file functions (calls & chained logic)
        for path, nids in file_to_nodes.items():
            func_ids = [nid for nid in nids if nid.startswith("func:") or "function" in nid]
            for i in range(len(func_ids) - 1):
                add_edge(func_ids[i], func_ids[i + 1], "calls", "#f59e0b")

        # 5. Connect Module nodes to Files
        module_nodes = [n for n in selected_nodes if n.type == NodeType.MODULE]
        for m in module_nodes:
            for f_node in selected_nodes:
                if f_node.type == NodeType.FILE and f_node.location.path:
                    if m.name.lower() in f_node.location.path.lower():
                        add_edge(m.id, f_node.id, "imports", "#ec4899")

        # 6. Read verified edges from persistent registry if present
        if self.repo_root:
            edges_file = self.repo_root / ".registry" / "edges.json"
            if edges_file.exists():
                try:
                    persisted_edges = json.loads(edges_file.read_text(encoding="utf-8"))
                    for pe in persisted_edges:
                        s = pe.get("source") or pe.get("source_id")
                        t = pe.get("target") or pe.get("target_id")
                        rel = pe.get("type", "calls")
                        add_edge(s, t, rel, "#f59e0b" if rel == "calls" else "#a855f7")
                except Exception:
                    pass

        return {
            "nodes": nodes_list,
            "edges": edges_list,
            "total_nodes_in_registry": len(all_nodes),
            "rendered_nodes_count": len(nodes_list),
            "rendered_edges_count": len(edges_list),
        }

    def run_orchestration(self, req_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute orchestrated pipeline across all agent layers."""
        if not self.orchestrator or not self.repo_root:
            raise ValueError("No active repository loaded. Please submit a GitHub repository URL to analyze first.")

        with self._lock:
            plan_req = TaskPlanRequest(
                task_title=req_data.get("task_title", "Full Codebase Security & Health Audit"),
                user_prompt=req_data.get("description", "Automated multi-agent audit run from Web UI"),
                target_files=req_data.get("target_files", []),
                budget_limit_usd=req_data.get("budget_limit_usd"),
                require_human_approval=req_data.get("require_human_approval", True),
                repo_root=str(self.repo_root),
            )

            out = self.orchestrator.execute(plan_req)
            out_dict = out.model_dump()
            self.latest_output = out_dict
            self._save_cached_report(out_dict)
            return out_dict

    def clear_repository(self) -> Dict[str, Any]:
        """Clear active repository and reset store to a clean empty state."""
        with self._lock:
            self.repo_root = None
            self.store = CodeRegistryStore()
            self.orchestrator = None
            self.latest_output = None
            self.approval_decisions.clear()
        return {
            "success": True,
            "message": "Repository removed. System is ready for any GitHub repository URL.",
            "repo_name": None,
        }

    def record_approval(self, option_id: str, decision: str, notes: str = "") -> Dict[str, Any]:
        """Store Human-in-the-Loop authorization decisions."""
        with self._lock:
            record = {
                "option_id": option_id,
                "decision": decision.upper(),
                "timestamp": time.time(),
                "notes": notes,
                "applied": False,
            }
            self.approval_decisions[option_id] = record
            return record

    def analyze_github_repo(
        self,
        url: str,
        depth: int = 1,
        run_orchestration: bool = True,
    ) -> Dict[str, Any]:
        """Clone an arbitrary GitHub repository, scan AST structure, link relationships, and audit."""
        url = url.strip()
        if not url.startswith("http://") and not url.startswith("https://") and not url.startswith("git@"):
            raise ValueError(f"Invalid git repository URL: '{url}'")

        repo_name = url.rstrip("/").split("/")[-1].replace(".git", "")
        if not repo_name or any(c in repo_name for c in ("..", "/", "\\")):
            raise ValueError(f"Invalid repository name derived from URL: '{repo_name}'")

        dest_dir = (Path("repos") / repo_name).resolve()
        dest_dir.parent.mkdir(parents=True, exist_ok=True)

        agent_logger.info("control", "ui_server", "github.clone_started", f"Cloning {url} into {dest_dir} (depth={depth})...")
        if not dest_dir.exists():
            cmd = ["git", "clone", f"--depth={depth}", url, str(dest_dir)]
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode != 0:
                raise RuntimeError(f"Git clone failed: {res.stderr.strip() or res.stdout.strip()}")
            agent_logger.info("control", "ui_server", "github.cloned", f"Successfully cloned {repo_name} to {dest_dir}")
        else:
            agent_logger.info("control", "ui_server", "github.reusing", f"Found existing clone at {dest_dir}")

        storage_file = dest_dir / ".registry" / "registry.json"
        target_store = CodeRegistryStore(persistence_path=str(storage_file))
        target_keeper = RegistryKeeper(store=target_store, repo_root=str(dest_dir))
        target_mapper = StructureMapper(store=target_store, repo_root=str(dest_dir))
        target_linker = RelationshipLinker(store=target_store, repo_root=str(dest_dir))
        target_dsm = DataServiceMapper(store=target_store, repo_root=str(dest_dir))

        agent_logger.info("control", "ui_server", "github.ast_scan", f"Extracting AST nodes for {repo_name}...")
        mapper_out, _ = target_mapper.map_and_register(registry_keeper=target_keeper, repo_shard=".")

        agent_logger.info("control", "ui_server", "github.code_edges", f"Extracting call, import, and test edges...")
        linker_out, _ = target_linker.link_and_register(registry_keeper=target_keeper)

        agent_logger.info("control", "ui_server", "github.system_edges", f"Mapping APIs, DB tables, and queries...")
        dsm_out, _ = target_dsm.map_and_register(registry_keeper=target_keeper)

        with self._lock:
            self.repo_root = dest_dir
            self.store = target_store
            self.orchestrator = OrchestratorAgent(registry_store=self.store, repo_root=str(dest_dir))

        report_summary = None
        if run_orchestration:
            agent_logger.info("control", "ui_server", "github.orchestrating", f"Executing multi-agent audit on {repo_name}...")
            plan_req = TaskPlanRequest(
                task_title=f"Full Multi-Agent Audit for {repo_name}",
                repo_root=str(dest_dir),
                execution_mode=TaskExecutionMode.PARALLEL,
                cost_budget_usd=10.0,
            )
            out = self.orchestrator.execute(plan_req)
            self.latest_output = out.model_dump()
            self._save_cached_report(self.latest_output)
            if out.unified_report:
                report_summary = {
                    "overall_health_score": out.unified_report.overall_health_score,
                    "findings_count": len(out.unified_report.ranked_findings),
                    "remediations_count": len(out.unified_report.remediation_options),
                }

        return {
            "success": True,
            "repo_name": repo_name,
            "repo_root": str(dest_dir),
            "url": url,
            "files_scanned": mapper_out.stats.get("files_scanned", 0),
            "nodes_count": len(mapper_out.nodes),
            "edges_count": len(linker_out.verified_edges),
            "apis_count": len(dsm_out.api_nodes),
            "tables_count": len(dsm_out.table_nodes),
            "report_summary": report_summary,
        }


class MultiAgentRequestHandler(http.server.BaseHTTPRequestHandler):
    """Custom request handler dispatching REST API routes and serving static UI assets."""

    server_app: MultiAgentUIServer

    def _set_headers(self, status: int = 200, content_type: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()

    def do_OPTIONS(self) -> None:
        self._set_headers(204)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        # ------------------ REST APIs ------------------
        if path == "/api/status":
            payload = self.server_app.get_status_payload()
            self._set_headers(200, "application/json")
            self.wfile.write(json.dumps(payload).encode("utf-8"))
            return

        elif path == "/api/graph":
            limit = int(query.get("limit", ["400"])[0])
            filter_type = query.get("type", [None])[0]
            payload = self.server_app.get_graph_payload(node_limit=limit, filter_type=filter_type)
            self._set_headers(200, "application/json")
            self.wfile.write(json.dumps(payload).encode("utf-8"))
            return

        elif path == "/api/report":
            out = self.server_app.latest_output
            if out:
                self._set_headers(200, "application/json")
                self.wfile.write(json.dumps(out).encode("utf-8"))
            else:
                self._set_headers(200, "application/json")
                self.wfile.write(json.dumps({
                    "status": "NO_RUN_YET",
                    "message": "No orchestration runs recorded yet. Trigger one via /api/orchestrate or UI.",
                }).encode("utf-8"))
            return

        elif path == "/api/approvals":
            self._set_headers(200, "application/json")
            self.wfile.write(json.dumps(self.server_app.approval_decisions).encode("utf-8"))
            return

        elif path == "/api/logs":
            limit = int(query.get("limit", ["50"])[0])
            records: List[Dict[str, Any]] = []
            if self.server_app.repo_root:
                log_file = self.server_app.repo_root / "logs" / "agents.jsonl"
                if log_file.exists():
                    try:
                        lines = log_file.read_text(encoding="utf-8").strip().splitlines()
                        for line in lines[-limit:]:
                            if line.strip():
                                records.append(json.loads(line))
                    except Exception as e:
                        records.append({"error": f"Failed to parse log: {e}"})
            self._set_headers(200, "application/json")
            self.wfile.write(json.dumps({"logs": records}).encode("utf-8"))
            return

        elif path in ("/api/registry", "/api/registry/download"):
            nodes = self.server_app.store.list_all(include_deleted=False)
            repo_name = self.server_app.repo_root.name if self.server_app.repo_root else "codebase"
            format_type = query.get("format", ["json"])[0].lower()

            # Retrieve complete graph with relational edges connecting modules, functions, files, APIs, tables
            graph_data = self.server_app.get_graph_payload(node_limit=10000)
            edges = graph_data.get("edges", [])
            node_map = {n.id: n for n in nodes}

            # Pre-aggregate relations per node for fast lookup
            calls_map: Dict[str, List[str]] = defaultdict(list)
            called_by_map: Dict[str, List[str]] = defaultdict(list)
            imports_map: Dict[str, List[str]] = defaultdict(list)
            imported_by_map: Dict[str, List[str]] = defaultdict(list)
            queries_map: Dict[str, List[str]] = defaultdict(list)
            routes_to_map: Dict[str, List[str]] = defaultdict(list)
            container_map: Dict[str, str] = {}

            for e in edges:
                s, t, rel = e.get("source"), e.get("target"), e.get("type")
                if not s or not t:
                    continue
                s_name = node_map[s].name if s in node_map else s
                t_name = node_map[t].name if t in node_map else t

                if rel == "calls":
                    if t_name not in calls_map[s]:
                        calls_map[s].append(t_name)
                    if s_name not in called_by_map[t]:
                        called_by_map[t].append(s_name)
                elif rel == "routes_to":
                    if t_name not in routes_to_map[s]:
                        routes_to_map[s].append(t_name)
                    if s_name not in called_by_map[t]:
                        called_by_map[t].append(s_name)
                elif rel == "queries":
                    if t_name not in queries_map[s]:
                        queries_map[s].append(t_name)
                elif rel == "imports":
                    if t_name not in imports_map[s]:
                        imports_map[s].append(t_name)
                    if s_name not in imported_by_map[t]:
                        imported_by_map[t].append(s_name)
                elif rel in ("contains", "defines"):
                    container_map[t] = s_name

            # Also check node metadata for persisted incoming/outgoing edges from RelationshipLinker
            for n in nodes:
                out_edges = n.metadata.get("outgoing_edges", [])
                for oe in out_edges:
                    tgt = oe.get("target_id")
                    etype = oe.get("type")
                    tgt_name = node_map[tgt].name if tgt in node_map else tgt
                    if etype == "calls" and tgt_name not in calls_map[n.id]:
                        calls_map[n.id].append(tgt_name)
                        called_by_map[tgt].append(n.name)
                    elif etype == "imports" and tgt_name not in imports_map[n.id]:
                        imports_map[n.id].append(tgt_name)
                        imported_by_map[tgt].append(n.name)

            # FORMAT 1: Dedicated Call Graph / Interconnection Matrix CSV
            if format_type in ("callgraph_csv", "relations_csv", "callgraph"):
                import csv
                import io
                buf = io.StringIO()
                writer = csv.writer(buf)
                writer.writerow([
                    "caller_id",
                    "caller_name",
                    "caller_type",
                    "caller_path",
                    "callee_id",
                    "callee_name",
                    "callee_type",
                    "callee_path",
                    "relationship",
                    "line_number"
                ])

                for e in edges:
                    s_id = e.get("source")
                    t_id = e.get("target")
                    rel = e.get("type", "relates")
                    s_node = node_map.get(s_id)
                    t_node = node_map.get(t_id)

                    s_name = s_node.name if s_node else s_id
                    t_name = t_node.name if t_node else t_id
                    s_type = s_node.type.value if s_node and hasattr(s_node.type, "value") else (str(s_node.type) if s_node else "")
                    t_type = t_node.type.value if t_node and hasattr(t_node.type, "value") else (str(t_node.type) if t_node else "")
                    s_path = s_node.location.path if s_node and s_node.location else ""
                    t_path = t_node.location.path if t_node and t_node.location else ""
                    line_num = s_node.location.start_line if s_node and s_node.location else ""

                    writer.writerow([
                        s_id,
                        s_name,
                        s_type,
                        s_path,
                        t_id,
                        t_name,
                        t_type,
                        t_path,
                        rel,
                        line_num,
                    ])

                csv_bytes = buf.getvalue().encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="callgraph_{repo_name}.csv"')
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(csv_bytes)
                return

            # FORMAT 2: Enriched Entity Registry CSV with who-calls-who columns
            elif format_type in ("csv", "entities_csv"):
                import csv
                import io
                buf = io.StringIO()
                writer = csv.writer(buf)
                writer.writerow([
                    "id",
                    "name",
                    "type",
                    "path",
                    "start_line",
                    "end_line",
                    "signature",
                    "calls",
                    "called_by",
                    "routes_to",
                    "queries_tables",
                    "imports",
                    "imported_by",
                    "parent_container",
                    "hash",
                    "status"
                ])
                for n in nodes:
                    writer.writerow([
                        n.id,
                        n.name,
                        n.type.value if hasattr(n.type, "value") else str(n.type),
                        n.location.path if n.location else "",
                        n.location.start_line if n.location else "",
                        n.location.end_line if n.location else "",
                        n.location.signature if n.location else "",
                        "; ".join(calls_map.get(n.id, [])),
                        "; ".join(called_by_map.get(n.id, [])),
                        "; ".join(routes_to_map.get(n.id, [])),
                        "; ".join(queries_map.get(n.id, [])),
                        "; ".join(imports_map.get(n.id, [])),
                        "; ".join(imported_by_map.get(n.id, [])),
                        container_map.get(n.id, ""),
                        n.hash or "",
                        n.status.value if hasattr(n.status, "value") else str(n.status),
                    ])
                csv_bytes = buf.getvalue().encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="registry_{repo_name}.csv"')
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(csv_bytes)
                return

            # FORMAT 3: Enriched JSON Payload
            nodes_data = []
            for n in nodes:
                dump = n.model_dump()
                dump["relations"] = {
                    "calls": calls_map.get(n.id, []),
                    "called_by": called_by_map.get(n.id, []),
                    "routes_to": routes_to_map.get(n.id, []),
                    "queries_tables": queries_map.get(n.id, []),
                    "imports": imports_map.get(n.id, []),
                    "imported_by": imported_by_map.get(n.id, []),
                    "parent_container": container_map.get(n.id, ""),
                }
                nodes_data.append(dump)

            payload = {
                "repository": repo_name,
                "extracted_at": time.time(),
                "total_entities": len(nodes_data),
                "total_relationships": len(edges),
                "entities": nodes_data,
                "relationships": edges,
                "call_graph": [e for e in edges if e.get("type") == "calls"],
            }
            res_bytes = json.dumps(payload, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Disposition", f'attachment; filename="registry_{repo_name}.json"')
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(res_bytes)
            return

        # ------------------ Static Files ------------------
        rel_path = path.lstrip("/")
        if not rel_path or rel_path == "index.html":
            target_file = self.server_app.static_dir / "index.html"
        else:
            target_file = self.server_app.static_dir / rel_path

        if target_file.exists() and target_file.is_file():
            mime_type, _ = mimetypes.guess_type(str(target_file))
            mime_type = mime_type or "text/plain"
            if mime_type.startswith("text/") or mime_type in ("application/javascript", "application/json"):
                mime_type += "; charset=utf-8"

            self._set_headers(200, mime_type)
            with open(target_file, "rb") as f:
                self.wfile.write(f.read())
        else:
            self._set_headers(404, "application/json")
            self.wfile.write(json.dumps({"error": "Resource not found", "path": path}).encode("utf-8"))

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len).decode("utf-8") if content_len > 0 else "{}"
        try:
            req_data = json.loads(body) if body.strip() else {}
        except json.JSONDecodeError:
            self._set_headers(400, "application/json")
            self.wfile.write(json.dumps({"error": "Invalid JSON body"}).encode("utf-8"))
            return

        if path == "/api/orchestrate":
            try:
                result = self.server_app.run_orchestration(req_data)
                self._set_headers(200, "application/json")
                self.wfile.write(json.dumps(result).encode("utf-8"))
            except Exception as e:
                self._set_headers(500, "application/json")
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
            return

        elif path == "/api/approve":
            opt_id = req_data.get("option_id")
            decision = req_data.get("decision", "APPROVE")
            notes = req_data.get("notes", "")
            if not opt_id:
                self._set_headers(400, "application/json")
                self.wfile.write(json.dumps({"error": "Missing 'option_id' field"}).encode("utf-8"))
                return

            res = self.server_app.record_approval(opt_id, decision, notes)
            self._set_headers(200, "application/json")
            self.wfile.write(json.dumps({
                "status": "recorded",
                "record": res,
                "message": f"Remediation option {opt_id} marked as {decision.upper()}",
            }).encode("utf-8"))
            return

        elif path == "/api/github-analyze":
            url = req_data.get("url")
            depth = int(req_data.get("depth", 1))
            run_audit = bool(req_data.get("run_orchestration", True))
            if not url:
                self._set_headers(400, "application/json")
                self.wfile.write(json.dumps({"error": "Missing 'url' field"}).encode("utf-8"))
                return
            try:
                result = self.server_app.analyze_github_repo(url=url, depth=depth, run_orchestration=run_audit)
                self._set_headers(200, "application/json")
                self.wfile.write(json.dumps(result).encode("utf-8"))
            except Exception as e:
                self._set_headers(500, "application/json")
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
            return

        elif path == "/api/clear-repo":
            result = self.server_app.clear_repository()
            self._set_headers(200, "application/json")
            self.wfile.write(json.dumps(result).encode("utf-8"))
            return

        self._set_headers(404, "application/json")
        self.wfile.write(json.dumps({"error": "Unknown POST endpoint"}).encode("utf-8"))

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress standard BaseHTTPRequestHandler console noise in favor of AgentLogger."""
        return


def run_server(
    repo_root: str = ".",
    storage_path: Optional[str] = None,
    port: int = 8080,
    host: str = "127.0.0.1",
    open_browser: bool = False,
) -> MultiAgentUIServer:
    """Instantiate and run the Multi-Agent UI HTTP Server."""
    app = MultiAgentUIServer(repo_root=repo_root, storage_path=storage_path, port=port, host=host)

    class CustomHandler(MultiAgentRequestHandler):
        pass

    class CustomServer(http.server.ThreadingHTTPServer):
        allow_reuse_address = True

    CustomHandler.server_app = app

    httpd = CustomServer((host, port), CustomHandler)
    app.httpd = httpd
    app.port = httpd.server_address[1]

    agent_logger.info("control", "ui_server", "server.started", f"Multi-Agent Dashboard listening on http://{host}:{app.port}")

    if open_browser:
        import webbrowser
        threading.Thread(target=lambda: (time.sleep(0.5), webbrowser.open(f"http://{host}:{app.port}")), daemon=True).start()

    return app
