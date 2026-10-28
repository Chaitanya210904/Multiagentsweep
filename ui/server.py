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
        repo_root: str = ".",
        storage_path: Optional[str] = None,
        port: int = 8080,
        host: str = "127.0.0.1",
    ):
        self.repo_root = Path(repo_root).resolve()
        self.port = port
        self.host = host
        self.store = CodeRegistryStore(persistence_path=storage_path)
        self.orchestrator = OrchestratorAgent(registry_store=self.store, repo_root=str(self.repo_root))
        self.static_dir = Path(__file__).parent / "static"
        self._lock = threading.Lock()
        self.latest_output: Optional[Dict[str, Any]] = None
        self.approval_decisions: Dict[str, Dict[str, Any]] = {}
        self.httpd: Optional[http.server.ThreadingHTTPServer] = None
        self._load_cached_report()

    def _load_cached_report(self) -> None:
        """Attempt to restore the latest generated report from disk cache."""
        cache_file = self.repo_root / ".registry" / "latest_report.json"
        if cache_file.exists():
            try:
                data = json.loads(cache_file.read_text(encoding="utf-8"))
                self.latest_output = data
            except Exception as e:
                agent_logger.warning("control", "ui_server", "report.cache_load_failed", str(e))

    def _save_cached_report(self, data: Dict[str, Any]) -> None:
        """Persist latest orchestration run to disk cache."""
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
            "repo_root": str(self.repo_root),
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

        # Generate hierarchy edges (File -> contained entities) & inter-entity links
        edges_list = []
        edge_set = set()

        for path, nids in file_to_nodes.items():
            file_id = f"file:{path.lstrip('./')}"
            if file_id in node_id_set:
                for child_id in nids:
                    if child_id != file_id and child_id in node_id_set:
                        edge_key = f"{file_id}->{child_id}"
                        if edge_key not in edge_set:
                            edge_set.add(edge_key)
                            edges_list.append({
                                "source": file_id,
                                "target": child_id,
                                "type": "contains",
                                "color": "#334155",
                            })

        # Connect API / DB tables to source files
        for n in selected_nodes:
            if n.type in (NodeType.API, NodeType.TABLE) and n.location.path:
                file_id = f"file:{n.location.path.lstrip('./')}"
                if file_id in node_id_set:
                    edge_key = f"{n.id}->{file_id}"
                    if edge_key not in edge_set:
                        edge_set.add(edge_key)
                        edges_list.append({
                            "source": n.id,
                            "target": file_id,
                            "type": "defines",
                            "color": "#10b981" if n.type == NodeType.API else "#3b82f6",
                        })

        return {
            "nodes": nodes_list,
            "edges": edges_list,
            "total_nodes_in_registry": len(all_nodes),
            "rendered_nodes_count": len(nodes_list),
            "rendered_edges_count": len(edges_list),
        }

    def run_orchestration(self, req_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute orchestrated pipeline across all agent layers."""
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
            log_file = self.server_app.repo_root / "logs" / "agents.jsonl"
            records: List[Dict[str, Any]] = []
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
