"""
Command Line Interface for Registry Keeper Agent.
Allows operators to scan real codebases, sync real git changes,
lookup nodes, and inspect audit change logs.
"""

import argparse
import json
from pathlib import Path
import sys
from typing import Optional

from agents.graph.registry_keeper import RegistryKeeper
from agents.graph.structure_mapper import StructureMapper
from core.logger import AgentLogger, agent_logger
from models.registry import NodeType
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

    # agent logs
    logs_parser = subparsers.add_parser("logs", parents=[common_parser], help="Display structured agent execution and milestone logs")
    logs_parser.add_argument("--limit", type=int, default=30, help="Number of log records to show (default: 30)")
    logs_parser.add_argument("--agent", default=None, help="Filter by agent ID (e.g., 'registry_keeper')")
    logs_parser.add_argument("--layer", default=None, help="Filter by layer (e.g., 'graph')")
    logs_parser.add_argument("--level", default=None, help="Filter by level (INFO, WARNING, ERROR)")
    logs_parser.add_argument("--raw", action="store_true", help="Print raw JSON format")

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


if __name__ == "__main__":
    main()
