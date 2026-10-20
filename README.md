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

## Agent Specification: Structure Mapper (`structure_mapper`)

| Field | Value |
|---|---|
| **ID** | `structure_mapper` |
| **Name** | Structure Mapper |
| **Layer** | `graph` |
| **Role** | Graph agent 1: nodes |
| **Description** | Walks one shard at a time and creates a node for every file, class and function. Registers each node before it is used anywhere. |
| **Access** | `read-only` (cannot write directly to registry; proposes updates) |
| **Model Tier** | `small` |
| **Trigger** | After Registry Keeper; per changed shard |
| **Optional** | `false` |

### Inputs
- `repo_shard`: Target shard directory or list of files (e.g. `shard:agents/graph`).
- `language_configs`: Language parsing settings and extension mappings.
- `registry`: Read access to existing registry for checking existing nodes and diffing hashes.

### Outputs
- `nodes(id,type,path,signature,hash,summary)`: Extracted code nodes with signatures and SCIP symbols.
- `registry_update_proposals`: Formatted `CREATE` and `UPDATE` proposals for the Registry Keeper.

### Tools
- `tree_sitter`: Multi-language AST parser extracting files, classes, methods, and functions.
- `scip`: Source Code Intelligence Protocol symbol generator.
- `registry.lookup`: Read-only lookup to check existing nodes in the registry.
- `registry.propose`: Tool packaging nodes into formal `UpdateProposal` objects for Registry Keeper.

---

## Project Structure

```
multiagent/
├── agents/
│   ├── __init__.py
│   ├── base.py                   # BaseAgent & AgentMetadata protocol
│   └── graph/
│       ├── __init__.py
│       ├── registry_keeper.py    # Registry Keeper Agent
│       ├── cli.py                # Production CLI interface
│       └── __main__.py           # CLI entrypoint (python -m agents.graph)
├── core/
│   ├── __init__.py
│   └── exceptions.py             # UnauthorizedAccessError, RegistryError, etc.
├── models/
│   ├── __init__.py
│   └── registry.py               # Pydantic schemas: RegistryNode, NodeLocation, etc.
├── storage/
│   ├── __init__.py
│   └── registry_store.py         # Thread-safe persistent single source of truth store
├── tools/
│   ├── __init__.py
│   ├── registry_read.py          # registry.read tool
│   ├── registry_write.py         # registry.write tool (enforces registry-write access)
│   └── git_diff.py               # git.diff tool (real git diffs, working tree & commits)
├── tests/
│   ├── __init__.py
│   └── test_registry_keeper.py   # Complete test suite (12 unit & integration tests)
└── requirements.txt
```

---

## Production CLI Usage

The Registry Keeper can be executed directly from the terminal against any real repository:

```bash
# 1. Scan a real codebase (indexes files, classes, and functions with SHA-256 hashes)
python -m agents.graph.cli scan --repo .

# 2. View registry status & entity breakdown
python -m agents.graph.cli status

# 3. List tracked entities filtered by type
python -m agents.graph.cli list --type function

# 4. Lookup a specific canonical entity by ID
python -m agents.graph.cli get "func:agents/graph/registry_keeper.py:RegistryKeeper.execute"

# 5. Reconcile against git diff on commit or working tree
python -m agents.graph.cli sync

# 6. View historical audit change logs
python -m agents.graph.cli log --limit 10

# 7. Apply proposals from a JSON file
python -m agents.graph.cli apply /path/to/proposals.json
```

---

## Running Test Suite

```bash
PYTHONPATH=. .venv/bin/pytest tests/test_registry_keeper.py -v
```
