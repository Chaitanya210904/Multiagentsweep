"""
Tests for Web Application and Dashboard REST API (MultiAgentUIServer).
Verifies status summary, graph serialization, static asset delivery,
orchestrator dispatch, and human-in-the-loop remediation approvals.
"""

import json
from pathlib import Path
import threading
import time
import urllib.request
import pytest

from models.registry import NodeLocation, NodeType, RegistryNode
from storage.registry_store import CodeRegistryStore
from ui.server import MultiAgentUIServer, run_server


@pytest.fixture
def test_server(tmp_path):
    """Spin up an ephemeral in-process UI server on an available test port."""
    store_file = tmp_path / "registry.json"
    store = CodeRegistryStore(persistence_path=str(store_file))

    # Add sample nodes
    n1 = RegistryNode(
        id="file:src/auth.py",
        name="auth.py",
        type=NodeType.FILE,
        location=NodeLocation(path="src/auth.py"),
        hash="hash1",
    )
    n2 = RegistryNode(
        id="api:POST:/api/v1/login",
        name="POST /api/v1/login",
        type=NodeType.API,
        location=NodeLocation(path="src/auth.py", endpoint_method="POST", endpoint_route="/api/v1/login"),
        hash="hash2",
    )
    store.write_node(n1, access_token="registry-write", source_agent="structure_mapper")
    store.write_node(n2, access_token="registry-write", source_agent="data_service_mapper")
    store.save()

    app = run_server(
        repo_root=str(tmp_path),
        storage_path=str(store_file),
        port=0,
        host="127.0.0.1",
        open_browser=False,
    )

    t = threading.Thread(target=app.httpd.serve_forever, daemon=True)
    t.start()
    time.sleep(0.1)

    yield f"http://127.0.0.1:{app.port}", app

    if app.httpd:
        app.httpd.shutdown()
        app.httpd.server_close()


def test_ui_server_status_payload(test_server):
    """Verifies that status payload includes agent directory and node type tallies."""
    base_url, app = test_server
    req = urllib.request.Request(f"{base_url}/api/status")
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))

    assert data["status"] == "online"
    assert data["total_nodes"] == 2
    assert data["total_agents"] == 16
    assert data["type_counts"]["file"] == 1
    assert data["type_counts"]["api"] == 1

    agent_ids = {a["id"] for a in data["agents"]}
    assert "orchestrator" in agent_ids
    assert "result_aggregator_critic" in agent_ids
    assert "registry_keeper" in agent_ids
    assert "security" in agent_ids


def test_ui_server_graph_serialization(test_server):
    """Verifies that graph API returns formatted nodes and relational edges for canvas."""
    base_url, app = test_server
    req = urllib.request.Request(f"{base_url}/api/graph")
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))

    assert "nodes" in data
    assert "edges" in data
    assert data["rendered_nodes_count"] == 2
    assert len(data["edges"]) >= 1  # API linked to file

    node_ids = {n["id"] for n in data["nodes"]}
    assert "file:src/auth.py" in node_ids
    assert "api:POST:/api/v1/login" in node_ids


def test_ui_server_serves_static_assets(test_server):
    """Verifies that index.html, style.css, app.js, and graph.js are served with correct MIME types."""
    base_url, _ = test_server

    # HTML
    with urllib.request.urlopen(f"{base_url}/") as resp:
        assert resp.status == 200
        assert "text/html" in resp.headers.get("Content-Type", "")
        content = resp.read().decode("utf-8")
        assert "Multi-Agent AI Platform" in content

    # CSS
    with urllib.request.urlopen(f"{base_url}/style.css") as resp:
        assert resp.status == 200
        assert "text/css" in resp.headers.get("Content-Type", "")

    # JS App
    with urllib.request.urlopen(f"{base_url}/app.js") as resp:
        assert resp.status == 200
        assert "javascript" in resp.headers.get("Content-Type", "")

    # JS Graph
    with urllib.request.urlopen(f"{base_url}/graph.js") as resp:
        assert resp.status == 200
        assert "javascript" in resp.headers.get("Content-Type", "")


def test_ui_server_human_approval_api(test_server):
    """Verifies that operator decisions on remediation options are recorded."""
    base_url, app = test_server

    payload = json.dumps({
        "option_id": "OPT-001",
        "decision": "APPROVE",
        "notes": "Verified safe to execute",
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{base_url}/api/approve",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))

    assert data["status"] == "recorded"
    assert data["record"]["option_id"] == "OPT-001"
    assert data["record"]["decision"] == "APPROVE"

    # Confirm via approvals list
    with urllib.request.urlopen(f"{base_url}/api/approvals") as resp:
        assert resp.status == 200
        approvals = json.loads(resp.read().decode("utf-8"))
        assert "OPT-001" in approvals
        assert approvals["OPT-001"]["decision"] == "APPROVE"


def test_ui_server_github_analyze_api(test_server):
    """Verifies that the server handles GitHub repository cloning and analysis requests."""
    base_url, app = test_server

    # 1. Invalid URL validation
    bad_req = urllib.request.Request(
        f"{base_url}/api/github-analyze",
        data=json.dumps({"url": "ftp://bad-protocol.com/repo"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(bad_req) as resp:
            pass
        assert False, "Should have returned 500 error for invalid git URL"
    except urllib.error.HTTPError as err:
        assert err.code == 500
        body = json.loads(err.read().decode("utf-8"))
        assert "Invalid git repository URL" in body.get("error", "")

    # 2. Analyze existing repos/bottle
    valid_payload = json.dumps({
        "url": "https://github.com/bottlepy/bottle",
        "depth": 1,
        "run_orchestration": False,
    }).encode("utf-8")

    good_req = urllib.request.Request(
        f"{base_url}/api/github-analyze",
        data=valid_payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(good_req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))

    assert data["success"] is True
    assert data["repo_name"] == "bottle"
    assert data["nodes_count"] > 0
    assert "repos/bottle" in data["repo_root"]


def test_ui_server_clear_repo_api(test_server):
    """Verify that calling /api/clear-repo resets the active repository to clean blank state."""
    base_url, app = test_server

    req = urllib.request.Request(
        f"{base_url}/api/clear-repo",
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["success"] is True
        assert data["repo_name"] is None

    # Check status endpoint confirms blank state
    with urllib.request.urlopen(f"{base_url}/api/status") as resp:
        status_data = json.loads(resp.read().decode("utf-8"))
        assert status_data["is_blank"] is True
        assert status_data["repo_name"] is None


def test_ui_server_registry_download_api(test_server):
    """Verify that /api/registry and /api/registry/download export code entities and call graphs in JSON & CSV."""
    base_url, app = test_server

    # 1. Download as JSON (includes entities, relations, relationships, call_graph)
    with urllib.request.urlopen(f"{base_url}/api/registry/download?format=json") as resp:
        assert resp.status == 200
        assert "application/json" in resp.headers.get("Content-Type", "")
        assert "attachment" in resp.headers.get("Content-Disposition", "")
        data = json.loads(resp.read().decode("utf-8"))
        assert "entities" in data
        assert "relationships" in data
        assert "call_graph" in data
        assert data["total_entities"] == 2
        entity_ids = {e["id"] for e in data["entities"]}
        assert "file:src/auth.py" in entity_ids
        assert "api:POST:/api/v1/login" in entity_ids
        # Verify entity relations dict exists
        for ent in data["entities"]:
            assert "relations" in ent
            assert "calls" in ent["relations"]
            assert "called_by" in ent["relations"]

    # 2. Download as CSV (Enriched Entity list with calls, called_by, routes_to)
    with urllib.request.urlopen(f"{base_url}/api/registry/download?format=csv") as resp:
        assert resp.status == 200
        assert "text/csv" in resp.headers.get("Content-Type", "")
        assert "attachment" in resp.headers.get("Content-Disposition", "")
        csv_text = resp.read().decode("utf-8")
        lines = csv_text.strip().split("\n")
        assert len(lines) >= 3  # Header + 2 entities
        header = lines[0]
        assert "calls" in header
        assert "called_by" in header
        assert "routes_to" in header
        assert "file:src/auth.py" in csv_text
        assert "api:POST:/api/v1/login" in csv_text

    # 3. Download as Call Graph Matrix CSV (Who calls what row-by-row)
    with urllib.request.urlopen(f"{base_url}/api/registry/download?format=callgraph_csv") as resp:
        assert resp.status == 200
        assert "text/csv" in resp.headers.get("Content-Type", "")
        assert "callgraph_" in resp.headers.get("Content-Disposition", "")
        cg_text = resp.read().decode("utf-8")
        cg_lines = cg_text.strip().split("\n")
        assert len(cg_lines) >= 2  # Header + at least 1 edge (API defines/routes_to)
        cg_header = cg_lines[0]
        assert "caller_id" in cg_header
        assert "caller_name" in cg_header
        assert "callee_id" in cg_header
        assert "callee_name" in cg_header
        assert "relationship" in cg_header

