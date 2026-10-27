"""
Command Line Interface for Registry Keeper Agent.
Allows operators to scan real codebases, sync real git changes,
lookup nodes, and inspect audit change logs.
"""

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Optional

from agents.graph.registry_keeper import RegistryKeeper
from agents.graph.structure_mapper import StructureMapper
from agents.graph.relationship_linker import RelationshipLinker
from agents.graph.data_service_mapper import DataServiceMapper
from agents.understanding.impact_analyzer import ImpactAnalyzer
from agents.quality.architecture_review import ArchitectureReview
from agents.quality.code_quality import CodeQuality
from agents.safety.security_agent import SecurityAgent
from agents.runtime.observability_agent import ObservabilityAgent
from agents.runtime.scale_load_agent import ScaleLoadAgent
from agents.runtime.tech_scout_agent import TechScoutAgent
from agents.optional.test_generation_agent import TestGenerationAgent
from core.logger import AgentLogger, agent_logger
from models.architecture import ArchitectureReviewInput
from models.code_quality import CodeQualityInput
from models.data_service import DataServiceMapperInput, SystemEdgeType
from models.impact import ImpactAnalyzerInput
from models.observability import ObservabilityInput
from models.scale_load import ScaleLoadInput, TrafficTarget
from models.tech_scout import TechScoutInput
from models.test_generation import TestGenerationInput
from models.registry import NodeType
from models.relationship import EdgeType, RelationshipLinkerInput
from models.security import SecurityInput, VulnerabilitySeverity
from models.structure import RepoShard, StructureMapperInput
from storage.registry_store import CodeRegistryStore





def build_parser() -> argparse.ArgumentParser:
    common_parser = argparse.ArgumentParser(add_help=False)
    common_parser.add_argument(
        "--storage",
        default=None,
        help="Path to persistent registry JSON file (default: .registry/registry.json)",
    )
    common_parser.add_argument(
        "--repo",
        default=".",
        help="Path to repository root (default: current working directory)",
    )

    parser = argparse.ArgumentParser(
        prog="python -m agents.graph.cli",
        description="Registry Keeper: Single Source of Truth for Code Entities",
        parents=[common_parser],
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # scan
    scan_parser = subparsers.add_parser("scan", parents=[common_parser], help="Scan repository files and register AST nodes")
    scan_parser.add_argument("--path", default=None, help="Directory to scan (default: repo root)")

    # diff / sync
    diff_parser = subparsers.add_parser("sync", parents=[common_parser], help="Sync with git diffs and commit changes")
    diff_parser.add_argument("--commit", default=None, help="Specific commit or base commit")
    diff_parser.add_argument("--target", default=None, help="Target commit for commit range")
    diff_parser.add_argument("--staged", action="store_true", help="Inspect staged changes only")

    # status
    subparsers.add_parser("status", parents=[common_parser], help="Display summary statistics and health of the registry")

    # list
    list_parser = subparsers.add_parser("list", parents=[common_parser], help="List registered nodes")
    list_parser.add_argument("--type", choices=[t.value for t in NodeType], default=None, help="Filter by node type")
    list_parser.add_argument("--path", default=None, help="Filter by file path")

    # get
    get_parser = subparsers.add_parser("get", parents=[common_parser], help="Fetch a node by canonical ID")
    get_parser.add_argument("node_id", help="Canonical ID (e.g., 'file:src/main.py')")

    # log
    log_parser = subparsers.add_parser("log", parents=[common_parser], help="Display recent change log entries")
    log_parser.add_argument("--limit", type=int, default=20, help="Number of entries to show (default: 20)")

    # apply
    apply_parser = subparsers.add_parser("apply", parents=[common_parser], help="Apply proposals from a JSON file")
    apply_parser.add_argument("file", help="Path to proposals JSON file")

    # map-shard (Structure Mapper)
    shard_parser = subparsers.add_parser("map-shard", parents=[common_parser], help="Structure Mapper walks a shard and proposes nodes")
    shard_parser.add_argument("shard_path", help="Path to shard folder or file")
    shard_parser.add_argument("--register", action="store_true", help="Immediately register proposals with Registry Keeper")
    shard_parser.add_argument("--only-changed", action="store_true", help="Only propose modified or new nodes")

    # link-edges (Relationship Linker)
    link_parser = subparsers.add_parser("link-edges", parents=[common_parser], help="Relationship Linker creates calls, imports, inheritance, and test-to-code edges")
    link_parser.add_argument("--shard", default=None, help="Scope edge linking to a specific directory shard")
    link_parser.add_argument("--register", action="store_true", help="Immediately register verified edges with Registry Keeper")

    # map-system (Data & Service Mapper)
    sys_parser = subparsers.add_parser("map-system", parents=[common_parser], help="Data & Service Mapper maps APIs, DB tables/queries, and external services")
    sys_parser.add_argument("--shard", default=None, help="Scope system mapping to a specific directory shard")
    sys_parser.add_argument("--register", action="store_true", help="Immediately register system nodes and edges with Registry Keeper")

    # analyze-impact (Impact Analyzer)
    impact_parser = subparsers.add_parser("analyze-impact", parents=[common_parser], help="Impact Analyzer calculates blast-radius and determines agents to wake")
    impact_parser.add_argument("nodes", nargs="+", help="Canonical node IDs that changed (e.g. 'func:bottle.py:Router.add')")
    impact_parser.add_argument("--max-depth", type=int, default=6, help="Maximum dependency traversal depth (default: 6)")

    # review-architecture (Architecture Review)
    arch_parser = subparsers.add_parser("review-architecture", parents=[common_parser], help="Architecture Review checks layers, boundaries, cycles, coupling, and records ADRs")
    arch_parser.add_argument("--nodes", nargs="*", default=None, help="Scope review to specific node IDs (defaults to all)")
    arch_parser.add_argument("--threshold", type=int, default=15, help="Efferent coupling threshold for hotspots (default: 15)")
    arch_parser.add_argument("--no-cycles", action="store_true", help="Disable circular dependency checking")
    arch_parser.add_argument("--adrs", default=None, help="Path to existing ADRs directory or file")

    # check-quality (Code Quality)
    qual_parser = subparsers.add_parser("check-quality", parents=[common_parser], help="Code Quality finds complexity, duplication, smells, coverage gaps, and style issues")
    qual_parser.add_argument("files", nargs="*", default=None, help="Files to inspect (defaults to changed git files or active nodes)")
    qual_parser.add_argument("--coverage", default=None, help="Path to coverage report (JSON, XML, LCOV)")
    qual_parser.add_argument("--max-complexity", type=int, default=10, help="Maximum cyclomatic complexity threshold (default: 10)")
    qual_parser.add_argument("--max-lines", type=int, default=50, help="Maximum function lines threshold (default: 50)")

    # check-security (Security)
    sec_parser = subparsers.add_parser("check-security", parents=[common_parser], help="Security runs SAST, secret scanning, dependency CVE checks, and auth/input reviews")
    sec_parser.add_argument("files", nargs="*", default=None, help="Source code files to audit (defaults to registered files)")
    sec_parser.add_argument("--manifests", nargs="*", default=None, help="Dependency manifests (e.g. requirements.txt, package.json)")
    sec_parser.add_argument("--configs", nargs="*", default=None, help="Infrastructure configs (e.g. Dockerfile, k8s.yaml, .env)")
    sec_parser.add_argument("--fail-on", choices=["info", "low", "medium", "high", "critical"], default="high", help="Minimum severity to fail audit (default: high)")

    # read-observability (Observability)
    obs_parser = subparsers.add_parser("read-observability", parents=[common_parser], help="Observability reads logs, metrics, and traces and links problems back to code nodes")
    obs_parser.add_argument("--telemetry", default=None, help="Path to telemetry bundle file (JSON, log file, or trace file)")
    obs_parser.add_argument("--prom-url", default=None, help="Optional live Prometheus server URL (e.g. http://localhost:9090)")
    obs_parser.add_argument("--latency-threshold", type=float, default=500.0, help="Latency spike threshold in ms (default: 500)")
    obs_parser.add_argument("--error-rate-threshold", type=float, default=1.0, help="Error rate threshold in percentage (default: 1.0 percent)")

    # analyze-scale-load (Scale & Load)
    sl_parser = subparsers.add_parser("analyze-scale-load", parents=[common_parser], help="Scale & Load finds N+1 queries, missing indexes, caching gaps, runs load tests, and estimates capacity")
    sl_parser.add_argument("--hot-paths", nargs="*", default=None, help="Hot path node IDs or endpoint routes to evaluate")
    sl_parser.add_argument("--query-logs", default=None, help="Path to database query log file (SQL, log, JSON)")
    sl_parser.add_argument("--load-scripts", nargs="*", default=None, help="Paths to k6 (.js) or Locust (.py / stats.csv) load test scripts")
    sl_parser.add_argument("--target-rps", type=float, default=100.0, help="Target throughput in requests per second (default: 100.0)")
    sl_parser.add_argument("--target-p99", type=float, default=200.0, help="Target p99 latency SLA in ms (default: 200.0)")
    sl_parser.add_argument("--vus", type=int, default=10, help="Target concurrent virtual users (default: 10)")

    # scout-tech (Tech Scout)
    ts_parser = subparsers.add_parser("scout-tech", parents=[common_parser], help="Tech Scout researches better technologies and ranks them by benefit, effort, and risk with migration outlines")
    ts_parser.add_argument("--pain-points", nargs="*", default=None, help="Specific pain points or bottlenecks to address")
    ts_parser.add_argument("--focus", nargs="*", default=None, help="Focus areas (e.g. database, caching, framework)")
    ts_parser.add_argument("--max-options", type=int, default=5, help="Maximum number of options to rank (default: 5)")

    # generate-tests (Test Generation)
    tg_parser = subparsers.add_parser("generate-tests", parents=[common_parser], help="Test Generation Agent writes regression and unit tests for coverage gaps (after approval)")
    tg_parser.add_argument("--code", nargs="*", default=None, help="Target source code files or modules to cover")
    tg_parser.add_argument("--gaps", nargs="*", default=None, help="Coverage gaps, line ranges, or node IDs lacking tests")
    tg_parser.add_argument("--approve", action="store_true", help="Explicit operator approval to persist and execute tests on disk")
    tg_parser.add_argument("--dry-run", action="store_true", help="Synthesize and verify tests in-memory without disk write")
    tg_parser.add_argument("--output-dir", default=None, help="Target directory for generated test files (default: tests/generated/)")



    # agent logs
    logs_parser = subparsers.add_parser("logs", parents=[common_parser], help="Display structured agent execution and milestone logs")
    logs_parser.add_argument("--limit", type=int, default=30, help="Number of log records to show (default: 30)")
    logs_parser.add_argument("--agent", default=None, help="Filter by agent ID (e.g., 'registry_keeper')")
    logs_parser.add_argument("--layer", default=None, help="Filter by layer (e.g., 'graph')")
    logs_parser.add_argument("--level", default=None, help="Filter by level (INFO, WARNING, ERROR)")
    logs_parser.add_argument("--raw", action="store_true", help="Print raw JSON format")

    # test-github
    gh_parser = subparsers.add_parser("test-github", parents=[common_parser], help="Clone and run Structure Mapper + Registry Keeper on a real GitHub repository")
    gh_parser.add_argument("github_url", help="GitHub repository URL (e.g. 'https://github.com/psf/requests' or any public repo)")
    gh_parser.add_argument("--dest", default=None, help="Local directory to clone into (default: repos/<repo-name>)")
    gh_parser.add_argument("--depth", type=int, default=1, help="Git clone depth (default: 1 for fast cloning)")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    store = CodeRegistryStore(persistence_path=args.storage)
    keeper = RegistryKeeper(store=store, repo_root=args.repo)

    if args.command == "scan":
        target_path = args.path or args.repo
        print(f"🔍 Scanning repository at: {Path(target_path).resolve()}...")
        output = keeper.scan_repository(repo_path=target_path)
        print(f"✅ Scan complete!")
        print(f"   • Updated/registered nodes: {len(output.updated_registry)}")
        print(f"   • Unresolved items: {len(output.unresolved_items_list)}")
        print(f"   • Total active nodes in registry: {output.stats.get('total_active_nodes')}")
        if store.persistence_path:
            print(f"   • Persisted to: {store.persistence_path}")

    elif args.command == "sync":
        print(f"🔄 Reconciling with git diff...")
        output = keeper.sync_with_git(
            base_commit=args.commit,
            target_commit=args.target,
            staged=args.staged,
        )
        print(f"✅ Sync complete!")
        print(f"   • Mutated nodes: {len(output.updated_registry)}")
        print(f"   • Change log records: {len(output.change_log)}")
        for log in output.change_log:
            print(f"     [{log.action.value.upper()}] {log.node_id}")

    elif args.command == "status":
        nodes = store.list_all(include_deleted=False)
        change_logs = store.get_change_log()
        type_counts = {}
        for n in nodes:
            type_counts[n.type.value] = type_counts.get(n.type.value, 0) + 1

        print("📊 CODE REGISTRY STATUS:")
        print(f"   • Storage path: {store.persistence_path or ':memory:'}")
        print(f"   • Total active entities: {len(nodes)}")
        print(f"   • Total audit log entries: {len(change_logs)}")
        print("   • Breakdown by type:")
        for t, cnt in sorted(type_counts.items()):
            print(f"       - {t}: {cnt}")

    elif args.command == "list":
        node_type = NodeType(args.type) if args.type else None
        nodes = store.search(path=args.path, node_type=node_type, include_deleted=False)
        print(f"Found {len(nodes)} matching nodes:")
        for n in sorted(nodes, key=lambda x: x.id):
            print(f"  [{n.type.value:<8}] {n.id}  (hash: {n.hash[:10]}...)")

    elif args.command == "get":
        node = store.get(args.node_id)
        if not node:
            print(f"❌ Node '{args.node_id}' not found in registry.")
            sys.exit(1)
        print(json.dumps(node.model_dump(), indent=2))

    elif args.command == "log":
        entries = store.get_change_log(limit=args.limit)
        print(f"📜 Showing last {len(entries)} change log entries:")
        for e in entries:
            old_h = f"{e.old_hash[:8]}..." if e.old_hash else "None"
            new_h = f"{e.new_hash[:8]}..." if e.new_hash else "None"
            print(f"  • [{e.action.value.upper()}] {e.node_id} (by: {e.source_agent}) [{old_h} -> {new_h}]")

    elif args.command == "apply":
        print(f"📥 Applying proposals from: {args.file}...")
        output = keeper.apply_proposals_file(args.file)
        print(f"✅ Proposals applied!")
        print(f"   • Updated nodes: {len(output.updated_registry)}")
        print(f"   • Unresolved items: {len(output.unresolved_items_list)}")

    elif args.command == "map-shard":
        mapper = StructureMapper(store=store, repo_root=args.repo)
        shard = RepoShard.from_directory(args.shard_path, repo_root=args.repo)
        print(f"🗺️  Structure Mapper walking shard: {shard.shard_id} ({shard.root_path})...")

        if args.register:
            mapper_out, keeper_out = mapper.map_and_register(
                registry_keeper=keeper,
                repo_shard=shard,
                only_changed=args.only_changed,
            )
            print(f"✅ Mapped and registered with Registry Keeper!")
            print(f"   • Nodes extracted: {len(mapper_out.nodes)}")
            print(f"   • Proposals applied: {len(mapper_out.registry_update_proposals)}")
            print(f"   • Registry nodes updated: {len(keeper_out.updated_registry)}")
        else:
            inputs = StructureMapperInput(repo_shard=shard, only_changed=args.only_changed)
            output = mapper.execute(inputs)
            print(f"✅ Shard mapped successfully!")
            print(f"   • Nodes extracted: {len(output.nodes)}")
            print(f"   • Proposals generated: {len(output.registry_update_proposals)}")
            for p in output.registry_update_proposals[:10]:
                print(f"     [{p.action.value.upper()}] {p.node.id if p.node else p.proposal_id}")
            if len(output.registry_update_proposals) > 10:
                print(f"     ... and {len(output.registry_update_proposals) - 10} more")

    elif args.command == "logs":
        records = agent_logger.get_recent_logs(
            limit=args.limit,
            agent_id=args.agent,
            layer=args.layer,
            level=args.level,
        )
        if not records:
            print("📭 No agent logs found.")
        else:
            print(f"📜 Showing last {len(records)} agent events:")
            for r in records:
                if args.raw:
                    print(json.dumps(r.model_dump()))
                else:
                    agent_logger._write_to_console(r)

    elif args.command == "link-edges":
        linker = RelationshipLinker(store=store, repo_root=args.repo)
        if args.register:
            keeper = RegistryKeeper(store=store, repo_root=args.repo)
            linker_out, keeper_out = linker.link_and_register(registry_keeper=keeper, shard_path=args.shard)
            print(f"🔗 [Relationship Linker] Verified {len(linker_out.verified_edges)} code edges.")
            print(f"⚠️  [Relationship Linker] Unresolved queue: {len(linker_out.unresolved_link_queue)} links (never guessed).")
            print(f"✅ Registered {len(linker_out.registry_update_proposals)} edge proposals with Registry Keeper.")
        else:
            inputs = RelationshipLinkerInput(shard_path=args.shard)
            linker_out = linker.execute(inputs)
            print(f"🔗 [Relationship Linker] Verified {len(linker_out.verified_edges)} code edges:")
            for e in linker_out.verified_edges[:10]:
                print(f"   • [{e.type.value:<12}] {e.source_id}  -->  {e.target_id}")
            if len(linker_out.verified_edges) > 10:
                print(f"   ... and {len(linker_out.verified_edges) - 10} more.")
            print(f"⚠️  Unresolved link queue ({len(linker_out.unresolved_link_queue)} items - never guessed):")
            for u in linker_out.unresolved_link_queue[:5]:
                print(f"   • [{u.edge_type.value}] {u.source_path}: '{u.raw_target}' -> {u.reason}")

    elif args.command == "map-system":
        dsm = DataServiceMapper(store=store, repo_root=args.repo)
        if args.register:
            keeper = RegistryKeeper(store=store, repo_root=args.repo)
            dsm_out, keeper_out = dsm.map_and_register(registry_keeper=keeper, shard_path=args.shard)
            print(f"🌐 [Data & Service Mapper] Discovered {len(dsm_out.api_nodes)} APIs, {len(dsm_out.table_nodes)} DB tables, {len(dsm_out.service_nodes)} services.")
            print(f"🔗 [Data & Service Mapper] Verified system edges: {len(dsm_out.api_to_code_edges) + len(dsm_out.code_to_table_edges) + len(dsm_out.service_to_service_edges)}")
            print(f"⚠️  [Data & Service Mapper] Unresolved queue: {len(dsm_out.unresolved_queue)} system links (never guessed).")
            print(f"✅ Registered {len(dsm_out.registry_update_proposals)} proposals with Registry Keeper.")
        else:
            inputs = DataServiceMapperInput(shard_path=args.shard)
            dsm_out = dsm.execute(inputs)
            print(f"🌐 [Data & Service Mapper] Discovered System Entities:")
            print(f"   • APIs: {len(dsm_out.api_nodes)}")
            for a in dsm_out.api_nodes[:5]:
                print(f"     - [{a.location.endpoint_method}] {a.location.endpoint_route}")
            print(f"   • DB Tables: {len(dsm_out.table_nodes)}")
            for t in dsm_out.table_nodes[:5]:
                print(f"     - {t.name}")
            print(f"   • External Services: {len(dsm_out.service_nodes)}")
            for s in dsm_out.service_nodes[:5]:
                print(f"     - {s.name}")
            print(f"🔗 System Edges:")
            all_edges = dsm_out.api_to_code_edges + dsm_out.code_to_table_edges + dsm_out.service_to_service_edges
            for e in all_edges[:8]:
                print(f"   • [{e.type.value:<18}] {e.source_id}  -->  {e.target_id}")
            print(f"⚠️  Unresolved Queue ({len(dsm_out.unresolved_queue)} items - never guessed):")
            for u in dsm_out.unresolved_queue[:5]:
                print(f"   • [{u.edge_type.value}] {u.source_path}: '{u.raw_target}' -> {u.reason}")

    elif args.command == "analyze-impact":
        analyzer = ImpactAnalyzer(store=store, repo_root=args.repo)
        inp = ImpactAnalyzerInput(changed_nodes=args.nodes, max_depth=args.max_depth)
        res = analyzer.execute(inp)

        severity_colors = {
            "low": "🟢 LOW",
            "medium": "🟡 MEDIUM",
            "high": "🟠 HIGH",
            "critical": "🔴 CRITICAL",
        }
        sev_label = severity_colors.get(res.severity.value, res.severity.value.upper())

        print(f"\n💥 Blast Radius Analysis Report:")
        print(f"   • Score: {res.blast_radius_score}/100.0 [{sev_label}]")
        print(f"   • Changed Roots: {', '.join(res.affected_nodes_and_services.changed_roots)}")
        print(f"   • Total Affected Entities: {len(res.affected_nodes_and_services.all_affected_node_ids)}")
        print(f"   • Max Propagation Depth: {res.affected_nodes_and_services.max_propagation_depth}")

        aff = res.affected_nodes_and_services
        print(f"\n👥 Upstream Callers Impacted ({len(aff.callers)}):")
        for c in aff.callers[:5]:
            print(f"   • {c}")
        if len(aff.callers) > 5:
            print(f"   ... and {len(aff.callers) - 5} more.")

        print(f"\n🔻 Downstream Callees Impacted ({len(aff.callees)}):")
        for c in aff.callees[:5]:
            print(f"   • {c}")
        if len(aff.callees) > 5:
            print(f"   ... and {len(aff.callees) - 5} more.")

        print(f"\n🌐 System & Contract Impact:")
        print(f"   • Affected APIs: {len(aff.affected_apis)} -> {', '.join(aff.affected_apis[:3]) or 'None'}")
        print(f"   • Affected DB Tables: {len(aff.affected_tables)} -> {', '.join(aff.affected_tables[:3]) or 'None'}")
        print(f"   • Affected Services: {len(aff.affected_services)} -> {', '.join(aff.affected_services[:3]) or 'None'}")

        print(f"\n🧪 Test Coverage Breakdown:")
        print(f"   • Targeted Tests to Run: {len(aff.tests_to_run)} -> {', '.join(aff.tests_to_run[:3]) or 'None'}")
        print(f"   • Untested Modified Nodes (Risk): {len(aff.untested_nodes)} entities")

        print(f"\n⚡ Selective Agents to Wake ({len(res.agents_to_wake)}):")
        for w in res.agents_to_wake:
            print(f"   • [{w.priority.upper():<6}] [{w.layer.upper():<13}] Agent: '{w.agent_id}'")
            print(f"     Reason: {w.reason}")

    elif args.command == "review-architecture":
        reviewer = ArchitectureReview(store=store, repo_root=args.repo)
        existing_adrs = [args.adrs] if args.adrs else []
        inp = ArchitectureReviewInput(
            graph_slice=args.nodes,
            existing_adrs=existing_adrs,
            max_coupling_threshold=args.threshold,
            check_cycles=not args.no_cycles,
        )
        res = reviewer.execute(inp)

        print(f"\n🏛️  Architecture Review Report:")
        print(f"   • Clean Architecture Score: {res.clean_architecture_score}/100.0")
        print(f"   • Nodes Reviewed: {res.summary.get('nodes_reviewed')}")
        print(f"   • Total Violations: {len(res.violations)}")
        print(f"   • Layer Inversions: {res.summary.get('layer_inversions')}")
        print(f"   • Circular Dependencies: {res.summary.get('circular_dependencies')}")
        print(f"   • Excessive Coupling Hotspots: {res.summary.get('coupling_hotspots')}")

        if res.violations:
            print(f"\n⚠️  Architectural Violations ({len(res.violations)}):")
            for v in res.violations[:8]:
                print(f"   • [{v.severity.value.upper():<8}] [{v.type.value}] {v.message}")
                print(f"     💡 Remediation: {v.remediation}")
            if len(res.violations) > 8:
                print(f"   ... and {len(res.violations) - 8} more violations.")

        hotspots = [m for m in res.coupling_metrics if m.is_hotspot]
        if hotspots:
            print(f"\n🔥 Excessive Coupling Hotspots (Limit > {args.threshold}):")
            for h in hotspots[:5]:
                print(f"   • {h.entity_id} -> Ce={h.efferent_coupling}, Ca={h.afferent_coupling}, Instability={h.instability}")

        if res.draft_adrs:
            print(f"\n📜 Formulated Draft Architecture Decision Records ({len(res.draft_adrs)}):")
            for adr in res.draft_adrs:
                print(f"   • [{adr.id}] {adr.title} ({adr.status.value.upper()})")
                print(f"     Decision: {adr.decision}")

    elif args.command == "check-quality":
        cq = CodeQuality(store=store, repo_root=args.repo)
        target_files = args.files
        if not target_files:
            target_files = [n.location.path for n in store.list_all() if n.type == NodeType.FILE][:20]

        cov_reports = [args.coverage] if args.coverage else []
        inp = CodeQualityInput(
            changed_files=target_files,
            coverage_reports=cov_reports,
            max_cyclomatic_complexity=args.max_complexity,
            max_function_lines=args.max_lines,
        )
        res = cq.execute(inp)

        print(f"\n🔍 Code Quality Inspection Report:")
        print(f"   • Maintainability Rating: [{res.maintainability_rating}] (SonarQube SQALE)")
        print(f"   • Total Technical Debt: {res.technical_debt_minutes} minutes ({round(res.technical_debt_minutes / 60, 1)} hrs)")
        print(f"   • Files Analyzed: {res.stats.get('files_analyzed')}")
        print(f"   • Total Findings: {len(res.findings_with_file_and_line)}")

        if res.coverage_summary:
            print(f"\n🧪 Test Coverage:")
            print(f"   • Changed Files Coverage: {res.coverage_summary.changed_files_coverage_pct}%")
            print(f"   • Overall Coverage: {res.coverage_summary.overall_coverage_pct}%")

        if res.findings_with_file_and_line:
            print(f"\n⚠️  Quality Findings with File & Line:")
            for f in res.findings_with_file_and_line[:10]:
                print(f"   • [{f.severity.value.upper():<8}] [{f.category.value:<12}] {f.file_path}:{f.line_number} ({f.rule_id})")
                print(f"     {f.message}")
                print(f"     💡 Remediation: {f.remediation}")
            if len(res.findings_with_file_and_line) > 10:
                print(f"   ... and {len(res.findings_with_file_and_line) - 10} more findings.")

    elif args.command == "check-security":
        sec = SecurityAgent(registry_store=store, repo_root=args.repo)
        target_files = args.files
        if not target_files:
            target_files = [n.location.path for n in store.list_all() if n.type == NodeType.FILE][:20]

        manifests = args.manifests or []
        configs = args.configs or []
        fail_sev = VulnerabilitySeverity(args.fail_on)

        inp = SecurityInput(
            changed_code=target_files,
            dependency_manifests=manifests,
            configs=configs,
            fail_on_severity=fail_sev,
        )
        res = sec.execute(inp)

        status_icon = "✅ PASSED" if res.passed else "❌ FAILED"
        print(f"\n🛡️  Security Audit Report: {status_icon}")
        print(f"   • Security Health Score: {res.security_score}/100.0 (Grade: [{res.security_grade}])")
        print(f"   • Files Evaluated: {res.scanned_files_count}")
        print(f"   • Total Vulnerabilities: {len(res.vulnerabilities_with_severity_and_owasp_or_cve_reference)}")
        print(f"   • Severity Breakdown: 🔴 {res.critical_count} Critical, 🟠 {res.high_count} High, 🟡 {res.medium_count} Medium, 🟢 {res.low_count} Low, ℹ️ {res.info_count} Info")

        if res.vulnerabilities_with_severity_and_owasp_or_cve_reference:
            print(f"\n🚨 Pinpointed Vulnerabilities with OWASP/CVE References:")
            for v in res.vulnerabilities_with_severity_and_owasp_or_cve_reference[:10]:
                ref = v.cve_id or v.owasp_category or v.cwe_id or v.rule_id
                print(f"   • [{v.severity.value.upper():<8}] [{v.category.value:<16}] {v.file_path}:{v.line_number} ({ref})")
                print(f"     Title: {v.title}")
                print(f"     💡 Remediation: {v.remediation}")
                if v.code_snippet:
                    print(f"     Snippet: {v.code_snippet}")
            if len(res.vulnerabilities_with_severity_and_owasp_or_cve_reference) > 10:
                print(f"   ... and {len(res.vulnerabilities_with_severity_and_owasp_or_cve_reference) - 10} more vulnerabilities.")

    elif args.command == "read-observability":
        obs = ObservabilityAgent(
            registry_store=store,
            repo_root=args.repo,
            prometheus_url=args.prom_url,
        )
        telemetry_source = args.telemetry
        if not telemetry_source:
            default_telemetry = Path(args.repo) / "telemetry.json"
            telemetry_source = str(default_telemetry) if default_telemetry.exists() else {}

        inp = ObservabilityInput(
            opentelemetry_and_prometheus_data=telemetry_source,
            latency_threshold_ms=args.latency_threshold,
            error_rate_threshold_pct=args.error_rate_threshold,
        )
        res = obs.execute(inp)

        status_icon = "🟢 HEALTHY" if res.health_status == "HEALTHY" else ("🟡 DEGRADED" if res.health_status == "DEGRADED" else "🔴 CRITICAL")
        print(f"\n📊 Operational Observability Report: [{status_icon}]")
        print(f"   • Health Status: {res.health_status}")
        print(f"   • Metric Anomalies Detected: {len(res.error_and_latency_anomalies)}")
        print(f"   • Probable Root Causes Synthesized: {len(res.probable_root_cause_linked_to_nodes)}")
        print(f"   • Trace Spans Analyzed: {res.total_spans_analyzed}")
        print(f"   • Log Records Analyzed: {res.total_log_entries_analyzed}")
        print(f"   • Affected Services: {', '.join(res.affected_services) or 'None'}")

        if res.error_and_latency_anomalies:
            print(f"\n📈 Metric Anomalies:")
            for a in res.error_and_latency_anomalies[:5]:
                print(f"   • [{a.severity.value.upper():<8}] [{a.anomaly_type.value}] {a.metric_name}: {a.current_value} (baseline: {a.baseline_value}, {a.deviation_factor}x)")
                print(f"     {a.description}")

        if res.probable_root_cause_linked_to_nodes:
            print(f"\n🎯 Probable Root Causes Linked to Code Nodes:")
            for rc in res.probable_root_cause_linked_to_nodes[:5]:
                node_ref = f" -> Node: '{rc.linked_node_id}'" if rc.linked_node_id else ""
                print(f"   • [{rc.severity.value.upper():<8}] [{rc.confidence_score * 100:.0f}% confidence] {rc.title}{node_ref}")
                print(f"     Location: {rc.file_path}:{rc.line_number or 1}")
                print(f"     💡 Remediation: {rc.remediation_suggestion}")

    elif args.command == "analyze-scale-load":
        sl_agent = ScaleLoadAgent(
            registry_store=store,
            repo_root=args.repo,
        )
        hot_paths = args.hot_paths or []
        query_logs = args.query_logs or []
        load_scripts = args.load_scripts or []

        inp = ScaleLoadInput(
            graph_hot_paths=hot_paths,
            query_logs=query_logs,
            k6_or_locust_scripts=load_scripts,
            traffic_target=TrafficTarget(
                target_rps=args.target_rps,
                target_p99_latency_ms=args.target_p99,
                peak_concurrent_users=args.vus,
            ),
        )
        res = sl_agent.execute(inp)

        status_icon = "🟢 SUFFICIENT" if res.capacity_estimate.status.value == "CAPACITY_SUFFICIENT" else (
            "🟡 MARGINAL" if res.capacity_estimate.status.value == "CAPACITY_MARGINAL" else "🔴 DEFICIT"
        )
        print(f"\n⚡ Scale & Load Capacity Report: [{status_icon}]")
        print(f"   • Capacity Status: {res.capacity_estimate.status.value}")
        print(f"   • Current Max Throughput: {res.capacity_estimate.current_max_rps:.1f} RPS")
        print(f"   • Target Traffic SLA: {res.capacity_estimate.target_rps:.1f} RPS (Headroom: {res.capacity_estimate.headroom_multiplier}x, Gap: {res.capacity_estimate.capacity_gap_pct:+.1f}%)")
        print(f"   • Estimated Horizontal Scale: {res.capacity_estimate.estimated_required_instances} instance(s) required")
        print(f"   • Primary Limiting Factor: {res.capacity_estimate.limiting_factor}")
        print(f"   • Caching Strategy: {res.capacity_estimate.recommended_cache_strategy} (Estimated impact: {res.capacity_estimate.caching_throughput_multiplier}x throughput)")
        print(f"   • Bottlenecks Pinpointed: {len(res.bottlenecks)}")
        print(f"   • Load Tests Evaluated: {len(res.load_test_results)}")

        if res.bottlenecks:
            print(f"\n🚧 Detected Bottlenecks (N+1 queries, missing indexes, caching gaps):")
            for b in res.bottlenecks[:5]:
                node_ref = f" -> Node: '{b.linked_node_id}'" if b.linked_node_id else ""
                loc_ref = f" ({b.file_path}:{b.line_number})" if b.file_path else ""
                print(f"   • [{b.severity.value.upper():<8}] [{b.type.value}] {b.title}{node_ref}{loc_ref}")
                print(f"     {b.description}")
                print(f"     💡 Remediation: {b.remediation}")

        if res.capacity_estimate.recommended_indexes:
            print(f"\n🗄️  Recommended Index DDLs:")
            for idx in res.capacity_estimate.recommended_indexes[:5]:
                print(f"   • {idx}")

        if res.load_test_results:
            print(f"\n⏱️  Load Test Performance Results:")
            for lr in res.load_test_results:
                m = lr.metrics
                status = "PASS" if lr.thresholds_passed else "FAIL"
                print(f"   • [{lr.engine.upper()}] [{status}] RPS: {m.rps:.1f} | p50: {m.latency_p50_ms:.1f}ms | p95: {m.latency_p95_ms:.1f}ms | p99: {m.latency_p99_ms:.1f}ms | Error: {m.error_rate_pct:.2f}% ({lr.vus_or_users} VUs)")

    elif args.command == "scout-tech":
        scout = TechScoutAgent(
            registry_store=store,
            repo_root=args.repo,
        )
        pain_points = args.pain_points or []
        focus_areas = args.focus or []

        inp = TechScoutInput(
            pain_points_from_other_agents=pain_points,
            focus_areas=focus_areas,
            max_options=args.max_options,
        )
        res = scout.execute(inp)

        print(f"\n🔬 Tech Scout Technology Research Report:")
        print(f"   • Top Recommendation: {res.top_recommendation or 'None'}")
        print(f"   • Technologies Researched: {res.total_options_researched}")
        print(f"   • Pain Points Evaluated: {res.pain_points_addressed_count}")
        print(f"   • Summary: {res.executive_summary}")

        if res.ranked_options_with_migration_outline:
            print(f"\n🏆 Ranked Modern Technology Options:")
            for opt in res.ranked_options_with_migration_outline:
                print(f"\n   #{opt.rank} [{opt.category.value.upper()}] {opt.title}")
                print(f"      • Current: '{opt.current_tech}' ➔ Proposed: '{opt.proposed_tech}'")
                print(f"      • Composite Score: {opt.composite_score} (Benefit: {opt.benefit_score}/10, Effort: {opt.effort_score}/10, Risk: {opt.risk_score}/10)")
                print(f"      • Benefit: {opt.benefit_rationale}")
                print(f"      • Effort: {opt.effort_rationale}")
                print(f"      • Risk: {opt.risk_rationale}")
                if opt.addresses_pain_points:
                    print(f"      • Addresses: {'; '.join(opt.addresses_pain_points[:2])}")
                print(f"      • Migration Outline ({opt.migration_outline.estimated_total_effort_days} days est):")
                for phase in opt.migration_outline.phases:
                    print(f"        - Phase {phase.phase_number} ({phase.title}): {phase.description}")
                print(f"      • Rollback: {opt.migration_outline.rollback_strategy}")

    elif args.command == "generate-tests":
        test_agent = TestGenerationAgent(
            registry_store=store,
            repo_root=args.repo,
        )
        code_targets = args.code or []
        gap_targets = args.gaps or []

        inp = TestGenerationInput(
            code_under_test=code_targets,
            coverage_gaps=gap_targets,
            approved=args.approve,
            dry_run=args.dry_run,
            output_dir=args.output_dir,
        )
        res = test_agent.execute(inp)

        status_icon = "🟢 APPROVED" if res.approval_status == "approved" else "🟡 AWAITING APPROVAL"
        print(f"\n🧪 Test Generation Report: [{status_icon}]")
        print(f"   • Approval Status: {res.approval_status}")
        print(f"   • Total Test Cases Synthesized: {res.total_tests_generated}")
        print(f"   • Total Coverage Gaps Addressed: {res.total_gaps_addressed}")
        print(f"   • Test Files Produced: {len(res.new_test_files)}")

        if not args.approve:
            print("\n⚠️  NOTICE: Run with '--approve' to write test files to disk and execute automated verification.")

        for f in res.new_test_files:
            persist_tag = "💾 WRITTEN" if f.written_to_disk else "📝 IN-MEMORY DRAFT"
            ver_tag = f"[{f.verification_status.upper()}]"
            print(f"\n   • {persist_tag} {ver_tag} {f.test_file_path}")
            print(f"     Target Source: {f.source_file_path}")
            print(f"     Test Cases: {len(f.test_cases)}")
            for tc in f.test_cases:
                print(f"       - [{tc.test_type.value.upper()}] {tc.name} ({tc.description})")
            if f.test_runner_result:
                tr = f.test_runner_result
                print(f"     ⏱️  Runner: {tr.get('passed', 0)} passed, {tr.get('failed', 0)} failed ({tr.get('duration_ms', 0):.1f}ms)")

    elif args.command == "test-github":
        url = args.github_url
        repo_name = url.rstrip("/").split("/")[-1].replace(".git", "")
        dest_dir = Path(args.dest) if args.dest else Path("repos") / repo_name

        print(f"📦 [1/12] Preparing real GitHub repository: {url}")
        if not dest_dir.exists():
            print(f"⬇️  Cloning {url} into {dest_dir} (depth={args.depth})...")
            dest_dir.parent.mkdir(parents=True, exist_ok=True)
            res = subprocess.run(["git", "clone", f"--depth={args.depth}", url, str(dest_dir)], capture_output=True, text=True)
            if res.returncode != 0:
                print(f"❌ Git clone failed: {res.stderr}")
                sys.exit(1)
            print(f"✅ Successfully cloned {repo_name}!")
        else:
            print(f"📂 Found existing cloned repo at: {dest_dir}")

        storage_file = dest_dir / ".registry" / "registry.json"
        target_store = CodeRegistryStore(persistence_path=str(storage_file))
        target_keeper = RegistryKeeper(store=target_store, repo_root=str(dest_dir))
        target_mapper = StructureMapper(store=target_store, repo_root=str(dest_dir))
        target_linker = RelationshipLinker(store=target_store, repo_root=str(dest_dir))
        target_dsm = DataServiceMapper(store=target_store, repo_root=str(dest_dir))
        target_impact = ImpactAnalyzer(store=target_store, repo_root=str(dest_dir))
        target_arch = ArchitectureReview(store=target_store, repo_root=str(dest_dir))
        target_quality = CodeQuality(store=target_store, repo_root=str(dest_dir))
        target_sec = SecurityAgent(registry_store=target_store, repo_root=str(dest_dir))
        target_obs = ObservabilityAgent(registry_store=target_store, repo_root=str(dest_dir))
        target_scale = ScaleLoadAgent(registry_store=target_store, repo_root=str(dest_dir))
        target_scout = TechScoutAgent(registry_store=target_store, repo_root=str(dest_dir))
        target_testgen = TestGenerationAgent(registry_store=target_store, repo_root=str(dest_dir))

        print(f"\n🗺️  [2/13] Structure Mapper walking real GitHub repository...")
        mapper_out, keeper_out = target_mapper.map_and_register(
            registry_keeper=target_keeper,
            repo_shard=".",
        )

        print(f"\n🔗 [3/12] Relationship Linker analyzing and verifying code edges...")
        linker_out, keeper_edges_out = target_linker.link_and_register(
            registry_keeper=target_keeper,
        )

        print(f"\n🌐 [4/12] Data & Service Mapper mapping APIs, DB tables, queries & external services...")
        dsm_out, keeper_sys_out = target_dsm.map_and_register(
            registry_keeper=target_keeper,
        )

        total_system_edges = len(dsm_out.api_to_code_edges) + len(dsm_out.code_to_table_edges) + len(dsm_out.service_to_service_edges)

        print(f"\n💥 [5/12] Impact Analyzer evaluating blast-radius on core repository nodes...")
        sample_node = next((n.id for n in mapper_out.nodes if "router" in n.id.lower() or "app" in n.id.lower()), mapper_out.nodes[0].id)
        impact_out = target_impact.execute(ImpactAnalyzerInput(changed_nodes=[sample_node], max_depth=4))

        print(f"\n🏛️  [6/12] Architecture Review evaluating layers, cycles, coupling & drafting ADRs...")
        arch_out = target_arch.execute(ArchitectureReviewInput(check_cycles=True, max_coupling_threshold=20))

        print(f"\n🔍 [7/12] Code Quality inspecting complexity, duplication, smells & style...")
        sample_files = [n.location.path for n in mapper_out.nodes if n.type == NodeType.FILE][:10]
        quality_out = target_quality.execute(CodeQualityInput(changed_files=sample_files))

        print(f"\n🛡️  [8/12] Security scanning SAST, secrets, dependency CVEs & configs...")
        sec_out = target_sec.execute(SecurityInput(changed_code=sample_files))

        print(f"\n📡 [9/12] Observability linking operational telemetry, metrics & traces to code nodes...")
        obs_sample = {
            "metrics": [{"metric_name": "http_request_duration_seconds", "value": 0.12, "baseline": 0.10}],
            "logs": [],
            "traces": [],
        }
        obs_out = target_obs.execute(ObservabilityInput(opentelemetry_and_prometheus_data=obs_sample))

        print(f"\n⚡ [10/12] Scale & Load evaluating N+1 queries, missing indexes, caching gaps & capacity...")
        scale_out = target_scale.execute(ScaleLoadInput(
            graph_hot_paths=[sample_node],
            traffic_target=TrafficTarget(target_rps=100.0, target_p99_latency_ms=200.0),
        ))

        print(f"\n🔬 [11/13] Tech Scout researching modern upgrades for identified bottlenecks...")
        scout_pains = [b.title for b in scale_out.bottlenecks] or ["Throughput scaling and query latency"]
        scout_out = target_scout.execute(TechScoutInput(
            pain_points_from_other_agents=scout_pains,
            max_options=3,
        ))

        print(f"\n🧪 [12/13] Test Generation synthesizing unit tests for coverage gaps (approval gate & dry-run)...")
        testgen_targets = sample_files[:2] if sample_files else []
        testgen_gaps = impact_out.untested_nodes[:3] if impact_out.untested_nodes else []
        testgen_out = target_testgen.execute(TestGenerationInput(
            code_under_test=testgen_targets,
            coverage_gaps=testgen_gaps,
            approved=True,
            dry_run=True,
        ))

        print(f"\n📊 [13/13] Pipeline Complete Across Graph, Understanding, Quality, Safety, Runtime & Optional Layers:")
        print(f"   • Real source files scanned: {mapper_out.stats.get('files_scanned')}")
        print(f"   • Code nodes extracted: {len(mapper_out.nodes)}")
        print(f"   • System nodes: {len(dsm_out.api_nodes)} APIs, {len(dsm_out.table_nodes)} DB tables, {len(dsm_out.service_nodes)} services")
        print(f"   • Code edges verified: {len(linker_out.verified_edges)}")
        print(f"   • System edges verified: {total_system_edges}")
        print(f"   • Blast Radius Score: {impact_out.blast_radius_score}/100.0 ({impact_out.severity.value.upper()})")
        print(f"   • Clean Architecture Score: {arch_out.clean_architecture_score}/100.0")
        print(f"   • Code Maintainability Rating: [{quality_out.maintainability_rating}] ({quality_out.technical_debt_minutes} min debt)")
        print(f"   • Quality Findings Pinpointed: {len(quality_out.findings_with_file_and_line)}")
        print(f"   • Security Health Score: {sec_out.security_score}/100.0 (Grade: [{sec_out.security_grade}])")
        print(f"   • Security Vulnerabilities: {len(sec_out.vulnerabilities_with_severity_and_owasp_or_cve_reference)} (Crit: {sec_out.critical_count}, High: {sec_out.high_count})")
        print(f"   • Runtime Health Status: [{obs_out.health_status}]")
        print(f"   • Capacity Status: [{scale_out.capacity_estimate.status.value}] ({scale_out.capacity_estimate.current_max_rps:.1f} max RPS vs {scale_out.capacity_estimate.target_rps:.1f} target)")
        print(f"   • Top Tech Recommendation: {scout_out.top_recommendation or 'None'}")
        print(f"   • Generated Test Cases: {testgen_out.total_tests_generated} ({len(testgen_out.new_test_files)} file(s), Status: [{testgen_out.approval_status}])")
        print(f"   • Saved to: {storage_file}")

        print(f"\n🎉 SUCCESS: All 12 Multi-Agent platform agents (Registry Keeper, Structure Mapper, Relationship Linker, Data & Service Mapper, Impact Analyzer, Architecture Review, Code Quality, Security, Observability, Scale & Load, Tech Scout, Test Generation) successfully processed real GitHub repository {url}!")






if __name__ == "__main__":
    main()
