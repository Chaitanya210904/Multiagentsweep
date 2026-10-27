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
4. **Quality Layer**:
   - `architecture_review` (**Architecture Review: Structure checker**) - *Implemented*
   - `code_quality` (**Code Quality: Maintainability checker**) - *Implemented*
5. **Safety Layer**:
   - `security` (**Security: Vulnerability scanner**) - *Implemented*
   - Company Rules, Compatibility, Validation
6. **Runtime Layer**:
   - `observability` (**Observability: Logs, metrics and traces reader**) - *Implemented*
   - `scale_load` (**Scale & Load: Capacity analyst**) - *Implemented*
   - `tech_scout` (**Tech Scout: Technology researcher**) - *Implemented*
   - DB Heartbeat
7. **Action Layer**: Implementer
8. **Optional Layer**: Test Generation, Cost & Token Governor, Documentation, Rollback/Release

---

## Agent Specification: Tech Scout (`tech_scout`)

| Field | Value |
|---|---|
| **ID** | `tech_scout` |
| **Name** | Tech Scout |
| **Layer** | `runtime` |
| **Role** | Technology researcher |
| **Description** | Researches better technology and ranks it by benefit, effort and risk. Reports only. |
| **Access** | `read-only` (strictly prohibited from mutating registry directly) |
| **Model Tier** | `medium` |
| **Trigger** | on request or scheduled |
| **Optional** | `false` |

### Inputs
- `stack_metadata`: Current technology stack metadata (languages, frameworks, DBs, dependencies).
- `pain_points_from_other_agents`: Collected pain points, bottlenecks, and violations from other agents.
- `focus_areas`: Optional technology domains to prioritize (e.g. `database`, `caching`, `framework`).
- `max_options`: Maximum number of options to rank (default: 5).

### Outputs
- `ranked_options_with_migration_outline`: Technological alternatives ranked by composite score `(benefit * 2) - (effort) - (risk)` with complete multi-phase migration roadmaps, verification criteria, and rollback strategies.
- `total_options_researched`: Total number of technology candidates evaluated.
- `pain_points_addressed_count`: Count of active pain points resolved by proposed upgrades.
- `top_recommendation`: Highest-ranked technology recommendation.
- `executive_summary`: Strategic research synthesis for engineering leadership.

### Tools
- `web.search`: Searches technical documentation, package registries, ecosystem benchmarks, and architecture guides for technology alternatives.
- `docs.fetch`: Fetches official technical documentation, migration guides, changelogs, and release notes from URLs or local files.

---

## Agent Specification: Scale & Load (`scale_load`)

| Field | Value |
|---|---|
| **ID** | `scale_load` |
| **Name** | Scale & Load |
| **Layer** | `runtime` |
| **Role** | Capacity analyst |
| **Description** | Finds N+1 queries, missing indexes and caching gaps, runs load tests, and estimates capacity. |
| **Access** | `read-only` (strictly prohibited from mutating registry directly) |
| **Model Tier** | `medium` |
| **Trigger** | on request and before release |
| **Optional** | `false` |

### Inputs
- `graph_hot_paths`: High-frequency code/system nodes, routes, or transaction paths in the graph.
- `query_logs`: Database slow query logs, ORM statement traces, or execution log records.
- `k6_or_locust_scripts`: k6 JavaScript scripts or Locust Python scenario files or configs.
- `traffic_target`: Target traffic requirements (`target_rps`, `peak_concurrent_users`, `target_p99_latency_ms`).

### Outputs
- `bottlenecks`: Pinpointed N+1 queries, missing indexes, caching gaps, and hot paths with exact file/line locations and remediation strategies.
- `load_test_results`: Outcomes and HTTP latency distributions from k6 and Locust load tests (RPS, p50, p90, p95, p99, error rate).
- `capacity_estimate`: Capacity projection, max sustainable throughput (RPS), headroom multiplier, and horizontal scaling estimates.

### Tools
- `k6`: Executes or evaluates k6 load testing scripts, parses k6 execution metrics, and verifies performance thresholds.
- `locust`: Executes or evaluates Locust load testing scenarios, parses Locust CSV/JSON execution stats, and profiles endpoint throughput.
- `graph.traverse`: Traverses downstream dependencies from hot path roots to uncover complex multi-table query chains and services.

---

## Agent Specification: Observability (`observability`)

| Field | Value |
|---|---|
| **ID** | `observability` |
| **Name** | Observability |
| **Layer** | `runtime` |
| **Role** | Logs, metrics and traces reader |
| **Description** | Reads logs, metrics and traces and links problems back to code nodes. |
| **Access** | `read-only` (strictly prohibited from mutating registry directly) |
| **Model Tier** | `medium` |
| **Trigger** | timer and on alert |
| **Optional** | `false` |

### Inputs
- `opentelemetry_and_prometheus_data`: Telemetry bundle containing Prometheus metrics, OpenTelemetry structured logs, and distributed traces (JSON dict, file path, or log strings).
- `service_map`: Optional service topology map linking services, endpoints, and database tables.
- `latency_threshold_ms`: Latency spike threshold in milliseconds (default: 500ms).
- `error_rate_threshold_pct`: Error rate spike threshold in percentage (default: 1.0%).

### Outputs
- `error_and_latency_anomalies`: Detected metric spikes, latency regressions, and operational deviations with severity and baseline deviation factor.
- `probable_root_cause_linked_to_nodes`: Pinpointed root causes connected to exact code registry nodes and line numbers with confidence scores, trace/span IDs, and actionable remediation suggestions.
- `health_status`: Overall runtime system health assessment (`HEALTHY`, `DEGRADED`, or `CRITICAL`).
- `affected_services`: List of unique services affected by active anomalies or incidents.

### Tools
- `prometheus.query`: Live Prometheus HTTP API client and offline timeseries sample evaluator calculating error rates, request latency, CPU saturation, and database query slowdowns.
- `logs.search`: Real log parser extracting stack traces across Python tracebacks, JavaScript/Node.js stack frames, Java exceptions, and structured OpenTelemetry OTLP JSON logs.
- `traces.search`: Distributed trace evaluator analyzing OpenTelemetry OTLP, Jaeger, and Zipkin spans for error status, exception events, and latency bottlenecks exceeding thresholds.
- `registry.lookup`: Code registry lookup tool linking runtime problems directly back to canonical code nodes (`API`, `FUNCTION`, `CLASS`, `FILE`).

---

## Agent Specification: Security (`security`)

| Field | Value |
|---|---|
| **ID** | `security` |
| **Name** | Security |
| **Layer** | `safety` |
| **Role** | Vulnerability scanner |
| **Description** | Runs SAST, secret scanning, dependency CVE checks, and auth and input reviews. |
| **Access** | `read-only` (strictly prohibited from mutating registry directly) |
| **Model Tier** | `medium` |
| **Trigger** | on changed code or dependencies |
| **Optional** | `false` |

### Inputs
- `changed_code`: Source code files that changed or need security review.
- `dependency_manifests`: Manifest files (`requirements.txt`, `package.json`, `Pipfile`, `pyproject.toml`).
- `configs`: Configuration files (`Dockerfile`, `k8s.yaml`, `docker-compose.yml`, `.env`).
- `cve_feeds`: Optional custom CVE feeds, lists, or vulnerability database overrides.
- `fail_on_severity`: Minimum severity threshold to fail policy compliance (`HIGH` by default).

### Outputs
- `vulnerabilities_with_severity_and_owasp_or_cve_reference`: Pinpointed security vulnerabilities with severity, exact line numbers, and OWASP Top 10, CWE, or CVE references.
- `security_score`: Calibrated security health score from 0.0 to 100.0.
- `security_grade`: Security letter grade (`A`, `B`, `C`, `D`, `F`).
- `critical_count` / `high_count` / `medium_count` / `low_count` / `info_count`: Granular severity breakdown.
- `passed`: Boolean indicating if codebase passes security threshold.

### Tools
- `semgrep`: SAST engine analyzing code for SQLi, Command Injection, Insecure Deserialization, eval/exec, weak crypto, and missing authentication decorators.
- `gitleaks`: Dedicated secret scanner detecting API keys, AWS keys, GitHub tokens, Slack tokens, private keys, and database credentials with Shannon entropy filtering and snippet redaction.
- `trivy`: Dependency CVE auditor matching manifest versions against known CVEs and auditing Dockerfile/K8s/Compose misconfigurations.
- `registry.lookup`: Code registry lookup tool to enrich findings with public API route and database table context.

---

## Agent Specification: Code Quality (`code_quality`)

| Field | Value |
|---|---|
| **ID** | `code_quality` |
| **Name** | Code Quality |
| **Layer** | `quality` |
| **Role** | Maintainability checker |
| **Description** | Finds complexity, duplication, smells, test coverage gaps and style issues. |
| **Access** | `read-only` (strictly prohibited from mutating registry directly) |
| **Model Tier** | `small` |
| **Trigger** | On changed files |
| **Optional** | `false` |

### Inputs
- `changed_files`: List of files that changed or need maintainability review.
- `graph_neighbors`: Related neighbor nodes (callers, callees, tests) from Impact Analyzer.
- `coverage_reports`: Test coverage reports (coverage.py JSON, LCOV, Cobertura XML, or coverage dicts).

### Outputs
- `findings_with_file_and_line`: Detailed findings pinpointed to exact file paths and line numbers with remediations.
- `maintainability_rating`: SonarQube SQALE rating (`A`, `B`, `C`, `D`, `E`).
- `technical_debt_minutes`: Total estimated remediation time in minutes.
- `coverage_summary`: Coverage percentage across changed files and list of uncovered lines.

### Tools
- `sonarqube`: SonarQube quality engine inspecting cognitive complexity, code smells (long functions, too many parameters, broad exceptions, deep nesting) and cross-file block duplication.
- `ruff`: Official Ruff linter integration (and AST fallback) for unused imports, dead variables, and formatting.
- `eslint`: ESLint linter integration (and JS/TS rule fallback) for `no-var`, `no-eval`, `eqeqeq`, and debugger calls.
- `registry.lookup`: Code registry lookup tool to resolve neighbor nodes and locations.

---

## Agent Specification: Architecture Review (`architecture_review`)

| Field | Value |
|---|---|
| **ID** | `architecture_review` |
| **Name** | Architecture Review |
| **Layer** | `quality` |
| **Role** | Structure checker |
| **Description** | Checks layers, boundaries, circular dependencies and coupling, and records ADRs. |
| **Access** | `read-only` (strictly prohibited from mutating registry directly) |
| **Model Tier** | `medium` |
| **Trigger** | When impact analysis flags structural change |
| **Optional** | `false` |

### Inputs
- `graph_slice`: List of node IDs or `RegistryNode` objects in scope (defaults to all active nodes if omitted).
- `existing_adrs`: List of existing Architecture Decision Records (directory path or ADR models).

### Outputs
- `violations`: Detected breaches (`layer_inversion`, `circular_dependency`, `service_boundary_leak`, `excessive_coupling`, `forbidden_dependency`).
- `coupling_metrics`: Robert C. Martin's Package Coupling Metrics ($C_a$, $C_e$, Instability $I = \frac{C_e}{C_a + C_e}$).
- `draft_adrs`: Auto-generated Michael Nygard-compliant draft Architecture Decision Records.

### Tools
- `graph.traverse`: Graph traversal engine for dependency cycle detection and boundary checks.
- `registry.lookup`: Lookup node definitions, locations, and metadata.

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
