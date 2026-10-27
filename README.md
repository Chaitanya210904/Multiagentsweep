# Multi-Agent AI Platform

A distributed, layered multi-agent platform for automated codebase comprehension, verification, and transformation.

## Layer Overview
1. **Control Layer**: Orchestrator, Aggregator + Critic
2. **Graph Layer**:
   - `registry_keeper` (**Registry Keeper (the list)**) - *Implemented*
   - `structure_mapper` (**Structure Mapper: nodes**) - *Implemented*
   - `relationship_linker` (**Relationship Linker: code edges**) - *Implemented*
   - `data_service_mapper` (**Data & Service Mapper: system edges**) - *Implemented*
3. **Understanding Layer**:
   - `impact_analyzer` (**Impact Analyzer: Blast-radius finder**) - *Implemented*
4. **Quality Layer**: Architecture Review, Code Quality
5. **Safety Layer**: Security, Company Rules, Compatibility, Validation
6. **Runtime Layer**: DB Heartbeat, Observability, Scale & Load, Tech Scout
7. **Action Layer**: Implementer
8. **Optional Layer**: Test Generation, Cost & Token Governor, Documentation, Rollback/Release

---

## Agent Specification: Impact Analyzer (`impact_analyzer`)

| Field | Value |
|---|---|
| **ID** | `impact_analyzer` |
| **Name** | Impact Analyzer |
| **Layer** | `understanding` |
| **Role** | Blast-radius finder |
| **Description** | Walks the graph from changed nodes to find callers, callees and tests, then wakes only the affected agents. |
| **Access** | `read-only` (strictly prohibited from mutating registry directly) |
| **Model Tier** | `small` |
| **Trigger** | After graph is refreshed on a change |
| **Optional** | `false` |

### Inputs
- `changed_nodes`: List of node IDs or `RegistryNode` objects that were added, modified, or deleted.
- `graph`: Bidirectional dependency graph (accessed via `graph.traverse`).
- `registry`: The existing Code Registry (accessed via `registry.lookup`).

### Outputs
- `blast_radius_score`: Calibrated quantitative risk score from `0.0` (minimal) to `100.0` (catastrophic).
- `affected_nodes_and_services`: Categorized callers, callees, affected APIs, database tables, external services, and targeted tests.
- `agents_to_wake`: Selective wake directives targeting only downstream agents relevant to the change.

### Tools
- `graph.traverse`: Breadth-first bidirectional graph traversal (`upstream`, `downstream`, `both`) with cycle detection and path reconstruction.
- `registry.lookup`: Read-only entity lookup to inspect node metadata and edge attributes.

### Selective Agent Waking Matrix
| Agent | Layer | Trigger Condition |
|---|---|---|
| `orchestrator` | Control | Always woken to supervise downstream execution. |
| `code_quality` | Quality | Woken if code nodes (functions, classes, files) are affected. |
| `test_runner` | Quality | Woken if existing tests directly cover affected code (`tests_to_run`). |
| `test_generation` | Optional | Woken if modified code nodes lack test coverage (`untested_nodes`). |
| `security_agent` | Safety | Woken if APIs, external services are affected, or severity is `CRITICAL`. |
| `compatibility_agent` | Safety | Woken if public APIs or DB table schemas are affected. |
| `architecture_review` | Quality | Woken if blast radius score is `HIGH`/`CRITICAL` or service boundaries are crossed. |

---

## Agent Specification: Data & Service Mapper (`data_service_mapper`)

| Field | Value |
|---|---|
| **ID** | `data_service_mapper` |
| **Name** | Data & Service Mapper |
| **Layer** | `graph` |
| **Role** | Graph agent 3: system edges |
| **Description** | Maps APIs, DB tables and queries, queues, configs, env vars, external services and cross-service calls. Checks the registry before linking. |
| **Access** | `read-only` (strictly prohibited from mutating registry directly) |
| **Model Tier** | `small` |
| **Trigger** | After Structure Mapper; parallel with Relationship Linker |
| **Optional** | `false` |

### Inputs
- `api_specs`: API specifications, decorators, OpenAPI/Swagger definitions.
- `migrations`: SQL migration scripts (`CREATE TABLE`), Prisma schemas, ORM models.
- `query_code`: Source files containing SQL queries (`SELECT`, `INSERT`, `UPDATE`, `DELETE`) or ORM operations.
- `config_files`: `.env`, `docker-compose.yml`, `settings.py`, YAML/JSON configurations.
- `registry`: The existing Code Registry (accessible via `registry.lookup`).

### Outputs
- `api_to_code_edges`: Verified edges linking API endpoints to code handlers.
- `code_to_table_edges`: Verified edges linking query functions/methods to database tables.
- `service_to_service_edges`: Verified edges linking code to external services and queues.
- `unresolved_queue`: Missing endpoints (never guessed).
- `registry_update_proposals`: Update proposals for system nodes (`api`, `table`, `service`) and system edges.

### Tools
- `registry.lookup`: Lookup nodes and tables/services to verify endpoints.
- `registry.propose`: Package system nodes and edges into structured `UpdateProposal` objects.
- `graph.write_edge`: Create, validate, and record graph edges between verified endpoints.

---


---

## Agent Specification: Relationship Linker (`relationship_linker`)

| Field | Value |
|---|---|
| **ID** | `relationship_linker` |
| **Name** | Relationship Linker |
| **Layer** | `graph` |
| **Role** | Graph agent 2: code edges |
| **Description** | Creates calls, imports, inheritance and test-to-code edges. Looks up both endpoints in the registry first; missing endpoints go to the unresolved queue, never guessed. |
| **Access** | `read-only` (strictly prohibited from mutating registry directly) |
| **Model Tier** | `small` |
| **Trigger** | After Structure Mapper; parallel with Data & Service Mapper |
| **Optional** | `false` |

### Inputs
- `nodes_from_structure_mapper`: Nodes extracted from the repository shard.
- `registry_lookups`: Queries to verify endpoint existence in the Code Registry.

### Outputs
- `verified_edges`: List of verified `CodeEdge` objects (calls, imports, inheritance, test-to-code) where both endpoints exist in the registry.
- `unresolved_link_queue`: Potential links where one or both endpoints could not be verified (never guessed).
- `registry_update_proposals`: Formulated update proposals packaged for Registry Keeper.

### Tools
- `registry.lookup`: Lookup nodes by ID, path, or type to verify endpoints.
- `registry.propose`: Package verified edges into structured `UpdateProposal` objects.
- `graph.write_edge`: Create, validate, and record graph edges between verified endpoints.

---

## Production CLI Usage

The Graph Layer agents can be executed directly from the terminal against any real repository:

```bash
# 1. Scan a real codebase with Structure Mapper & Registry Keeper
python -m agents.graph.cli scan --repo .

# 2. Extract and verify code edges with Relationship Linker
python -m agents.graph.cli link-edges --repo .

# 3. Register verified edges directly with Registry Keeper
python -m agents.graph.cli link-edges --repo . --register

# 4. Test all 3 Graph Agents on any real GitHub repository
python -m agents.graph.cli test-github https://github.com/bottlepy/bottle

# 5. View live structured execution logs
python -m agents.graph.cli logs --limit 20
```

---

## Running Test Suite

```bash
PYTHONPATH=. .venv/bin/pytest tests/ -v
```


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
