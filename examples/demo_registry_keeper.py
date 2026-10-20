"""
Demonstration of the Registry Keeper Agent (Graph Layer).
Shows the end-to-end reconciliation cycle across all input sources:
- Structure Mapper node proposals
- Data & Service Mapper system proposals
- Relationship Linker edge validation and unresolved queue
- Git diffs (file rename & file deletion)
- Lookup queries and audit change logs
"""

import json
from pprint import pprint
from agents.graph.registry_keeper import REGISTRY_KEEPER_METADATA, RegistryKeeper
from models.registry import (
    GitDiffEntry,
    LookupQuery,
    NodeLocation,
    NodeType,
    RegistryKeeperInput,
    RegistryNode,
    UpdateProposal,
)
from storage.registry_store import CodeRegistryStore


def main():
    print("=" * 80)
    print(f"🤖 AGENT: {REGISTRY_KEEPER_METADATA.name} (ID: {REGISTRY_KEEPER_METADATA.id})")
    print(f"📁 Layer: {REGISTRY_KEEPER_METADATA.layer.upper()} | Role: {REGISTRY_KEEPER_METADATA.role}")
    print(f"🔐 Access: {REGISTRY_KEEPER_METADATA.access} | Tier: {REGISTRY_KEEPER_METADATA.model_tier}")
    print(f"⚡ Trigger: {REGISTRY_KEEPER_METADATA.trigger}")
    print("=" * 80)

    # 1. Initialize store and agent
    store = CodeRegistryStore()
    keeper = RegistryKeeper(store=store)

    print("\n--- STEP 1: Process Proposals from Structure Mapper (Agent 4) ---")
    structure_proposals = [
        UpdateProposal(
            source_agent="structure_mapper",
            node=RegistryNode(
                id="file:src/auth/jwt.py",
                name="jwt.py",
                type=NodeType.FILE,
                location=NodeLocation(path="src/auth/jwt.py"),
                hash=RegistryNode.generate_hash("import jwt\ndef decode(): pass"),
            ),
        ),
        UpdateProposal(
            source_agent="structure_mapper",
            node=RegistryNode(
                id="func:src/auth/jwt.py:verify_token",
                name="verify_token",
                type=NodeType.FUNCTION,
                location=NodeLocation(
                    path="src/auth/jwt.py",
                    start_line=15,
                    end_line=30,
                    signature="def verify_token(token: str) -> dict",
                ),
                hash=RegistryNode.generate_hash("def verify_token(token: str): ..."),
            ),
        ),
        UpdateProposal(
            source_agent="structure_mapper",
            node=RegistryNode(
                id="class:src/auth/jwt.py:TokenValidator",
                name="TokenValidator",
                type=NodeType.CLASS,
                location=NodeLocation(path="src/auth/jwt.py", start_line=35, end_line=60),
                hash=RegistryNode.generate_hash("class TokenValidator: ..."),
            ),
        ),
    ]

    out_step1 = keeper.execute(
        RegistryKeeperInput(update_proposals_from_structure_mapper=structure_proposals)
    )
    print(f"Registered {len(out_step1.updated_registry)} nodes from Structure Mapper:")
    for n in out_step1.updated_registry:
        print(f"  • [{n.type.value.upper()}] {n.id} (hash: {n.hash[:12]}...)")

    print("\n--- STEP 2: Process Proposals from Data & Service Mapper (Agent 6) ---")
    data_service_proposals = [
        UpdateProposal(
            source_agent="data_service_mapper",
            node=RegistryNode(
                id="api:POST:/api/v1/auth/login",
                name="Login API",
                type=NodeType.API,
                location=NodeLocation(
                    path="src/api/routes.py",
                    endpoint_method="POST",
                    endpoint_route="/api/v1/auth/login",
                ),
                hash=RegistryNode.generate_hash("POST /api/v1/auth/login -> verify_token"),
            ),
        ),
        UpdateProposal(
            source_agent="data_service_mapper",
            node=RegistryNode(
                id="table:users",
                name="users",
                type=NodeType.TABLE,
                location=NodeLocation(path="db/schema.sql", table_name="users"),
                hash=RegistryNode.generate_hash("CREATE TABLE users (id UUID, email VARCHAR);"),
            ),
        ),
        UpdateProposal(
            source_agent="data_service_mapper",
            node=RegistryNode(
                id="service:auth-service",
                name="auth-service",
                type=NodeType.SERVICE,
                location=NodeLocation(path="deploy/auth-service.yaml", service_name="auth-service"),
                hash=RegistryNode.generate_hash("service: auth-service port: 8080"),
            ),
        ),
    ]

    out_step2 = keeper.execute(
        RegistryKeeperInput(update_proposals_from_data_service_mapper=data_service_proposals)
    )
    print(f"Registered {len(out_step2.updated_registry)} system nodes from Data & Service Mapper:")
    for n in out_step2.updated_registry:
        print(f"  • [{n.type.value.upper()}] {n.id}")

    print("\n--- STEP 3: Process Proposals from Relationship Linker (Agent 5) ---")
    relationship_proposals = [
        # Valid link: from TokenValidator to verify_token
        UpdateProposal(
            source_agent="relationship_linker",
            details={
                "source_id": "class:src/auth/jwt.py:TokenValidator",
                "target_id": "func:src/auth/jwt.py:verify_token",
                "edge_type": "call",
            },
        ),
        # Invalid link: target endpoint does not exist! Should be sent to unresolved queue
        UpdateProposal(
            source_agent="relationship_linker",
            details={
                "source_id": "class:src/auth/jwt.py:TokenValidator",
                "target_id": "func:src/billing/stripe.py:charge_card",
                "edge_type": "call",
            },
        ),
    ]

    out_step3 = keeper.execute(
        RegistryKeeperInput(update_proposals_from_relationship_linker=relationship_proposals)
    )
    print(f"Verified edges updated: {len(out_step3.updated_registry)}")
    print(f"Unresolved items detected: {len(out_step3.unresolved_items_list)}")
    for item in out_step3.unresolved_items_list:
        print(f"  ⚠️  [UNRESOLVED] {item.item_id}")
        print(f"      Reason: {item.reason}")
        print(f"      Suggested Action: {item.suggested_action}")

    print("\n--- STEP 4: Process Git Diffs on Commit ---")
    git_diffs = [
        GitDiffEntry(change_type="R", old_path="src/auth/jwt.py", path="src/security/jwt.py"),
    ]
    out_step4 = keeper.execute(RegistryKeeperInput(git_diffs=git_diffs))
    print(f"Renamed file nodes: {len(out_step4.change_log)} changes recorded")
    for log in out_step4.change_log:
        print(f"  🔄 Action: {log.action.value} -> Node ID: {log.node_id}")

    print("\n--- STEP 5: Lookup Queries ---")
    lookups = [
        LookupQuery(id="file:src/security/jwt.py"),
        LookupQuery(id="api:POST:/api/v1/auth/login"),
        LookupQuery(id="table:nonexistent_table"),
    ]
    out_step5 = keeper.execute(RegistryKeeperInput(lookups=lookups))
    for q_id, res in out_step5.lookup_answers.items():
        status = f"✅ FOUND ({res.type.value}: {res.location.path})" if res else "❌ NOT FOUND"
        print(f"  🔍 Lookup '{q_id}': {status}")

    print("\n--- REGISTRY SUMMARY & STATS ---")
    total_nodes = store.count(include_deleted=False)
    print(f"Active Nodes Tracked: {total_nodes}")
    print(f"Total Change Log Records: {len(store.get_change_log())}")
    print("\nDone! Registry Keeper is operational as the single source of truth.")


if __name__ == "__main__":
    main()
