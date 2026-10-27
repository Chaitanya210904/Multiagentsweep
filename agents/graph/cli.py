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
from core.logger import AgentLogger, agent_logger
from models.data_service import DataServiceMapperInput, SystemEdgeType
from models.impact import ImpactAnalyzerInput
from models.registry import NodeType
from models.relationship import EdgeType, RelationshipLinkerInput
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

    elif args.command == "test-github":
        url = args.github_url
        repo_name = url.rstrip("/").split("/")[-1].replace(".git", "")
        dest_dir = Path(args.dest) if args.dest else Path("repos") / repo_name

        print(f"📦 [1/6] Preparing real GitHub repository: {url}")
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

        print(f"\n🗺️  [2/6] Structure Mapper walking real GitHub repository...")
        mapper_out, keeper_out = target_mapper.map_and_register(
            registry_keeper=target_keeper,
            repo_shard=".",
        )

        print(f"\n🔗 [3/6] Relationship Linker analyzing and verifying code edges...")
        linker_out, keeper_edges_out = target_linker.link_and_register(
            registry_keeper=target_keeper,
        )

        print(f"\n🌐 [4/6] Data & Service Mapper mapping APIs, DB tables, queries & external services...")
        dsm_out, keeper_sys_out = target_dsm.map_and_register(
            registry_keeper=target_keeper,
        )

        total_system_edges = len(dsm_out.api_to_code_edges) + len(dsm_out.code_to_table_edges) + len(dsm_out.service_to_service_edges)

        print(f"\n💥 [5/6] Impact Analyzer evaluating blast-radius on core repository nodes...")
        sample_node = next((n.id for n in mapper_out.nodes if "router" in n.id.lower() or "app" in n.id.lower()), mapper_out.nodes[0].id)
        impact_out = target_impact.execute(ImpactAnalyzerInput(changed_nodes=[sample_node], max_depth=4))

        print(f"\n📊 [6/6] Pipeline Complete Across Graph & Understanding Layers:")
        print(f"   • Real source files scanned: {mapper_out.stats.get('files_scanned')}")
        print(f"   • Code nodes extracted: {len(mapper_out.nodes)}")
        print(f"   • System nodes: {len(dsm_out.api_nodes)} APIs, {len(dsm_out.table_nodes)} DB tables, {len(dsm_out.service_nodes)} services")
        print(f"   • Code edges verified: {len(linker_out.verified_edges)}")
        print(f"   • System edges verified: {total_system_edges}")
        print(f"   • Simulated Changed Node: {sample_node}")
        print(f"   • Blast Radius Score: {impact_out.blast_radius_score}/100.0 ({impact_out.severity.value.upper()})")
        print(f"   • Selective Agents Woken: {[w.agent_id for w in impact_out.agents_to_wake]}")
        print(f"   • Saved to: {storage_file}")

        print(f"\n🎉 SUCCESS: All 5 Multi-Agent platform agents (Registry Keeper, Structure Mapper, Relationship Linker, Data & Service Mapper, Impact Analyzer) successfully processed real GitHub repository {url}!")





if __name__ == "__main__":
    main()
