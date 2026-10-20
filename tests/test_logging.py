"""
Tests for the central AgentLogger and BaseAgent lifecycle logging.
"""

from pathlib import Path
import pytest
import tempfile

from core.logger import AgentLogger, AgentLogRecord
from models.structure import RepoShard, StructureMapperInput
from storage.registry_store import CodeRegistryStore
from agents.graph.registry_keeper import RegistryKeeper
from agents.graph.structure_mapper import StructureMapper


def test_agent_logger_file_and_memory(tmp_path):
    """Verify AgentLogger writes structured JSONL records to disk and filters them."""
    log_file = tmp_path / "agents.jsonl"
    logger = AgentLogger(log_file=str(log_file), console_output=False)

    rec1 = logger.info("graph", "structure_mapper", "shard.started", "Started scanning shard", shard_id="shard:auth")
    rec2 = logger.warning("graph", "registry_keeper", "endpoint.unresolved", "Missing endpoint", endpoint_id="func:foo")
    rec3 = logger.error("safety", "security", "vulnerability.detected", "Found critical issue", severity="HIGH")

    assert log_file.exists()

    # Query all
    all_logs = logger.get_recent_logs(limit=10)
    assert len(all_logs) == 3

    # Query filtered by agent_id
    sm_logs = logger.get_recent_logs(agent_id="structure_mapper")
    assert len(sm_logs) == 1
    assert sm_logs[0].event == "shard.started"

    # Query filtered by layer
    graph_logs = logger.get_recent_logs(layer="graph")
    assert len(graph_logs) == 2

    # Query filtered by level
    err_logs = logger.get_recent_logs(level="ERROR")
    assert len(err_logs) == 1
    assert err_logs[0].agent_id == "security"


def test_base_agent_lifecycle_tracking(tmp_path):
    """Verify BaseAgent automatically emits started and completed events with execution time."""
    log_file = tmp_path / "agents.jsonl"
    store = CodeRegistryStore(persistence_path=":memory:")
    
    # Initialize StructureMapper with custom log file
    mapper = StructureMapper(store=store, repo_root=str(tmp_path))
    mapper.tracer = AgentLogger(log_file=str(log_file), console_output=False)

    # Create dummy shard
    test_file = tmp_path / "test.py"
    test_file.write_text("def ping(): pass\n")

    shard = RepoShard.from_directory(tmp_path, repo_root=str(tmp_path))
    output = mapper.execute(StructureMapperInput(repo_shard=shard))

    records = mapper.tracer.get_recent_logs(limit=20)
    events = [r.event for r in records]

    assert "agent.started" in events
    assert "shard.scanned" in events
    assert "nodes.extracted" in events
    assert "proposals.generated" in events
    assert "agent.completed" in events

    completed_rec = next(r for r in records if r.event == "agent.completed")
    assert completed_rec.duration_ms is not None
    assert completed_rec.duration_ms >= 0
