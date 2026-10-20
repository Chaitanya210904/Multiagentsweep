# Multi-Agent AI Platform

A distributed, layered multi-agent platform for automated codebase comprehension, verification, and transformation.

## Layer Overview
1. **Control Layer**: Orchestrator, Aggregator + Critic
2. **Graph Layer**:
   - `registry_keeper` (**Registry Keeper (the list)**) - *Implemented*
   - `structure_mapper` (Structure Mapper: nodes)
   - `relationship_linker` (Relationship Linker: code edges)
   - `data_service_mapper` (Data & Service Mapper: system edges)
3. **Understanding Layer**: Impact Analyzer
4. **Quality Layer**: Architecture Review, Code Quality
5. **Safety Layer**: Security, Company Rules, Compatibility, Validation
6. **Runtime Layer**: DB Heartbeat, Observability, Scale & Load, Tech Scout
7. **Action Layer**: Implementer
8. **Optional Layer**: Test Generation, Cost & Token Governor, Documentation, Rollback/Release

---

## Agent Specification: Registry Keeper (`registry_keeper`)

| Field | Value |
|---|---|
| **ID** | `registry_keeper` |
| **Name** | Registry Keeper |
| **Layer** | `graph` |
| **Role** | Single source of truth (the list) |
| **Description** | Owns the registry of every file, module, function, class, API, table and service with ID, location and hash. Only agent allowed to write to the registry. |
| **Access** | `registry-write` (exclusive mutation privilege) |
| **Model Tier** | `small` |
| **Trigger** | First on every commit; on every update proposal |
| **Optional** | `false` |

### Inputs
- `update_proposals_from_structure_mapper`: Proposed files, modules, classes, and functions.
- `update_proposals_from_relationship_linker`: Calls, imports, inheritance, and test-to-code links requiring endpoint verification.
- `update_proposals_from_data_service_mapper`: APIs, DB tables, queries, external services.
- `git_diffs`: Changed, added, deleted, or renamed files between commits.
- `deleted_or_renamed_files`: Explicit notifications of deleted/renamed entities.

### Outputs
- `updated_registry`: Registered nodes with verified canonical IDs, location, and SHA-256 hashes.
- `lookup_answers`: Exact resolution for querying agents.
- `unresolved_items_list`: Unresolvable proposals (e.g., links whose endpoints are not yet in the registry).
- `change_log`: Cryptographic and structural audit trail of all creations, updates, deletions, and renames.

### Tools
- `registry.read`: Read, search, and lookup nodes (accessible to all agents).
- `registry.write`: Create, mutate, delete, or rename nodes (restricted strictly to `registry-write` callers).
- `git.diff`: Inspect commit diffs and parse file modifications, deletions, and renames.

---

## Project Structure

```
multiagent/
├── agents/
│   ├── __init__.py
│   ├── base.py                   # BaseAgent & AgentMetadata protocol
│   └── graph/
│       ├── __init__.py
│       └── registry_keeper.py    # Registry Keeper Agent
├── core/
│   ├── __init__.py
│   └── exceptions.py             # UnauthorizedAccessError, RegistryError, etc.
├── models/
│   ├── __init__.py
│   └── registry.py               # Pydantic schemas: RegistryNode, NodeLocation, etc.
├── storage/
│   ├── __init__.py
│   └── registry_store.py         # Thread-safe single source of truth store
├── tools/
│   ├── __init__.py
│   ├── registry_read.py          # registry.read tool
│   ├── registry_write.py         # registry.write tool (checks registry-write access)
│   └── git_diff.py               # git.diff parser tool
├── tests/
│   ├── __init__.py
│   └── test_registry_keeper.py   # Complete test suite (10 test cases)
├── examples/
│   └── demo_registry_keeper.py   # End-to-end interactive demonstration
├── requirements.txt
└── pyproject.toml
```

---

## Running Tests & Demonstration

```bash
# Run tests
PYTHONPATH=. .venv/bin/pytest tests/test_registry_keeper.py -v

# Run the live demonstration
PYTHONPATH=. .venv/bin/python3 examples/demo_registry_keeper.py
```
