"""
Agent 6: Data & Service Mapper (Layer: Graph).
Role: Graph agent 3: system edges.
Description: Maps APIs, DB tables and queries, queues, configs, env vars, external services and cross-service calls.
Checks the registry before linking. Missing endpoints go to the unresolved queue, never guessed.
Access: read-only
"""

import ast
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from agents.base import AgentMetadata, BaseAgent
from models.data_service import (
    DataServiceMapperInput,
    DataServiceMapperOutput,
    SystemEdge,
    SystemEdgeType,
    UnresolvedSystemLink,
)
from models.registry import (
    NodeLocation,
    NodeType,
    RegistryKeeperInput,
    RegistryKeeperOutput,
    RegistryNode,
    UpdateProposal,
)
from storage.registry_store import CodeRegistryStore
from tools.graph_write_edge_tool import GraphWriteEdgeTool
from tools.registry_lookup_tool import RegistryLookupTool
from tools.registry_propose_tool import RegistryProposeTool


DATA_SERVICE_MAPPER_METADATA = AgentMetadata(
    id="data_service_mapper",
    name="Data & Service Mapper",
    layer="graph",
    role="Graph agent 3: system edges",
    description=(
        "Maps APIs, DB tables and queries, queues, configs, env vars, external services and cross-service calls. "
        "Checks the registry before linking."
    ),
    access="read-only",
    model_tier="small",
    inputs=[
        "api_specs",
        "migrations",
        "query_code",
        "config_files",
        "registry",
    ],
    outputs=[
        "api_to_code_edges",
        "code_to_table_edges",
        "service_to_service_edges",
        "unresolved_queue",
        "registry_update_proposals",
    ],
    tools=[
        "registry.lookup",
        "registry.propose",
        "graph.write_edge",
    ],
    trigger="after Structure Mapper; parallel with Relationship Linker",
    optional=False,
)


class DataServiceMapper(BaseAgent):
    """
    The Data & Service Mapper Agent discovers and verifies system-level entities and edges:
    - APIs: REST/gRPC endpoints mapped to code handlers (api_to_code_edges)
    - Data: DB tables and SQL/ORM queries mapped to tables (code_to_table_edges)
    - Services: External services, queues, configs, env vars (service_to_service_edges)
    Enforces the zero-guessing invariant by verifying endpoints against the registry.
    """

    def __init__(
        self,
        store: CodeRegistryStore,
        repo_root: Optional[str] = None,
        metadata: Optional[AgentMetadata] = None,
    ):
        super().__init__(metadata=metadata or DATA_SERVICE_MAPPER_METADATA)
        self.store = store
        self.repo_root = Path(repo_root).resolve() if repo_root else Path.cwd().resolve()

        # Tools (read-only safe)
        self.lookup_tool = RegistryLookupTool(store=self.store)
        self.propose_tool = RegistryProposeTool(source_agent=self.id)
        self.write_edge_tool = GraphWriteEdgeTool()

    def execute(self, inputs: Union[DataServiceMapperInput, Dict[str, Any]]) -> DataServiceMapperOutput:
        """
        Executes system entity discovery and edge linking:
        1. Discovers Database Tables from SQL migrations, schema files, and ORMs
        2. Discovers External Services and Queues from config/env files
        3. Discovers API Endpoints from decorators/specifications and links to handlers (api_to_code)
        4. Discovers SQL queries and ORM calls in code and links to tables (code_to_table)
        5. Discovers external client calls and links to services (service_to_service)
        6. Verifies endpoints in registry; routes unverified targets to unresolved queue (never guessed)
        7. Packages system nodes and edges as UpdateProposal objects for Registry Keeper
        """
        self.require_access("read-only")

        if isinstance(inputs, dict):
            inputs = DataServiceMapperInput.model_validate(inputs)

        t0 = self.log_started({"repo_root": str(self.repo_root)})

        try:
            api_nodes: List[RegistryNode] = []
            table_nodes: List[RegistryNode] = []
            service_nodes: List[RegistryNode] = []

            api_to_code_edges: List[SystemEdge] = []
            code_to_table_edges: List[SystemEdge] = []
            service_to_service_edges: List[SystemEdge] = []
            unresolved_queue: List[UnresolvedSystemLink] = []

            seen_edge_keys: Set[str] = set()

            # 1. Discover Database Tables from migrations & schemas
            self._discover_database_tables(
                migrations=inputs.migrations,
                table_nodes=table_nodes,
                shard_path=inputs.shard_path,
            )

            # 2. Discover External Services & Queues from configs & env vars
            self._discover_external_services(
                config_files=inputs.config_files,
                service_nodes=service_nodes,
                shard_path=inputs.shard_path,
            )

            # Cache discovered system node IDs for cross-verification
            known_tables = {t.name.lower(): t for t in table_nodes}
            for t_node in self.lookup_tool.find_by_type(NodeType.TABLE):
                known_tables[t_node.name.lower()] = t_node

            known_services = {s.name.lower(): s for s in service_nodes}
            for s_node in self.lookup_tool.find_by_type(NodeType.SERVICE):
                known_services[s_node.name.lower()] = s_node

            # 3. Discover API endpoints and link to code handlers (api_to_code)
            self._discover_apis_and_link(
                api_specs=inputs.api_specs,
                api_nodes=api_nodes,
                api_to_code_edges=api_to_code_edges,
                unresolved_queue=unresolved_queue,
                seen_edge_keys=seen_edge_keys,
                shard_path=inputs.shard_path,
            )

            # 4. Discover SQL queries and ORM calls in code and link to tables (code_to_table)
            self._discover_queries_and_link(
                query_code=inputs.query_code,
                known_tables=known_tables,
                code_to_table_edges=code_to_table_edges,
                unresolved_queue=unresolved_queue,
                seen_edge_keys=seen_edge_keys,
                shard_path=inputs.shard_path,
            )

            # 5. Discover external client calls and cross-service calls (service_to_service)
            self._discover_cross_service_calls(
                known_services=known_services,
                service_to_service_edges=service_to_service_edges,
                unresolved_queue=unresolved_queue,
                seen_edge_keys=seen_edge_keys,
                shard_path=inputs.shard_path,
            )

            # 6. Formulate Registry Update Proposals
            proposals: List[UpdateProposal] = []

            # Propose newly discovered system nodes (API, Table, Service)
            for node in api_nodes + table_nodes + service_nodes:
                proposals.append(self.propose_tool.propose_create(node))

            # Propose system edges
            all_system_edges = api_to_code_edges + code_to_table_edges + service_to_service_edges
            for edge in all_system_edges:
                proposals.append(self.propose_tool.propose_edge(edge))

            self.log_event(
                "system.nodes_discovered",
                f"Discovered {len(api_nodes)} APIs, {len(table_nodes)} DB tables, {len(service_nodes)} external services",
                apis=len(api_nodes),
                tables=len(table_nodes),
                services=len(service_nodes),
            )
            self.log_event(
                "system.edges_verified",
                f"Verified {len(all_system_edges)} system edges (API->Code: {len(api_to_code_edges)}, Code->Table: {len(code_to_table_edges)}, Service->Service: {len(service_to_service_edges)})",
                count=len(all_system_edges),
            )
            if unresolved_queue:
                self.log_event(
                    "system.unresolved_queued",
                    f"Identified {len(unresolved_queue)} unverified system references (routed to unresolved queue without guessing)",
                    count=len(unresolved_queue),
                )

            stats = {
                "apis_discovered": len(api_nodes),
                "tables_discovered": len(table_nodes),
                "services_discovered": len(service_nodes),
                "api_to_code_edges": len(api_to_code_edges),
                "code_to_table_edges": len(code_to_table_edges),
                "service_to_service_edges": len(service_to_service_edges),
                "unresolved_system_links": len(unresolved_queue),
                "total_proposals": len(proposals),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            self.log_completed(t0, stats)

            return DataServiceMapperOutput(
                api_nodes=api_nodes,
                table_nodes=table_nodes,
                service_nodes=service_nodes,
                api_to_code_edges=api_to_code_edges,
                code_to_table_edges=code_to_table_edges,
                service_to_service_edges=service_to_service_edges,
                unresolved_queue=unresolved_queue,
                registry_update_proposals=proposals,
                stats=stats,
            )
        except Exception as e:
            self.log_failed(t0, e)
            raise

    def map_and_register(
        self,
        registry_keeper: Any,
        api_specs: Optional[List[str]] = None,
        migrations: Optional[List[str]] = None,
        query_code: Optional[List[str]] = None,
        config_files: Optional[List[str]] = None,
        shard_path: Optional[str] = None,
    ) -> Tuple[DataServiceMapperOutput, RegistryKeeperOutput]:
        """
        End-to-end mapping workflow:
        1. Runs DataServiceMapper to discover system nodes and edges
        2. Transmits proposals (nodes + edges) to Registry Keeper
        3. Registry Keeper validates and registers nodes and edges atomically
        """
        inputs = DataServiceMapperInput(
            api_specs=api_specs,
            migrations=migrations,
            query_code=query_code,
            config_files=config_files,
            shard_path=shard_path,
        )
        mapper_out = self.execute(inputs)

        # Transmit proposals to Registry Keeper
        keeper_in = RegistryKeeperInput(
            update_proposals_from_data_service_mapper=mapper_out.registry_update_proposals
        )
        keeper_out = registry_keeper.execute(keeper_in)

        return mapper_out, keeper_out

    # --------------------------------------------------------------------------
    # Subroutines: 1. Database Table Discovery
    # --------------------------------------------------------------------------

    def _discover_database_tables(
        self,
        migrations: Optional[List[str]],
        table_nodes: List[RegistryNode],
        shard_path: Optional[str] = None,
    ) -> None:
        """Extracts database table schemas from SQL migration files, Prisma, and ORMs."""
        sql_pattern = re.compile(
            r"CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+[`\"']?([a-zA-Z0-9_]+)[`\"']?\s*\(",
            re.IGNORECASE,
        )
        orm_table_pattern = re.compile(
            r"__tablename__\s*=\s*['\"]([a-zA-Z0-9_]+)['\"]",
        )

        target_files = self._collect_files(migrations, [".sql", ".py", ".prisma"], shard_path=shard_path)
        seen_tables: Set[str] = set()

        for file_path in target_files:
            rel_path = str(file_path.relative_to(self.repo_root)) if file_path.is_relative_to(self.repo_root) else str(file_path)
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            lines = content.splitlines()

            # SQL CREATE TABLE
            if file_path.suffix.lower() == ".sql":
                for idx, line in enumerate(lines, start=1):
                    match = sql_pattern.search(line)
                    if match:
                        tbl_name = match.group(1).lower()
                        if tbl_name not in seen_tables:
                            seen_tables.add(tbl_name)
                            h = hashlib.sha256(f"table:{tbl_name}:{rel_path}:{idx}".encode("utf-8")).hexdigest()
                            table_node = RegistryNode(
                                id=f"table:{tbl_name}",
                                name=tbl_name,
                                type=NodeType.TABLE,
                                location=NodeLocation(
                                    path=rel_path,
                                    start_line=idx,
                                    table_name=tbl_name,
                                    signature=f"CREATE TABLE {tbl_name}",
                                ),
                                hash=h,
                                metadata={"schema_type": "sql_migration"},
                            )
                            table_nodes.append(table_node)

            # Python ORM Models
            elif file_path.suffix.lower() in (".py", ".pyi"):
                for idx, line in enumerate(lines, start=1):
                    match = orm_table_pattern.search(line)
                    if match:
                        tbl_name = match.group(1).lower()
                        if tbl_name not in seen_tables:
                            seen_tables.add(tbl_name)
                            h = hashlib.sha256(f"table:{tbl_name}:{rel_path}:{idx}".encode("utf-8")).hexdigest()
                            table_node = RegistryNode(
                                id=f"table:{tbl_name}",
                                name=tbl_name,
                                type=NodeType.TABLE,
                                location=NodeLocation(
                                    path=rel_path,
                                    start_line=idx,
                                    table_name=tbl_name,
                                    signature=f"__tablename__ = '{tbl_name}'",
                                ),
                                hash=h,
                                metadata={"schema_type": "python_orm"},
                            )
                            table_nodes.append(table_node)

    # --------------------------------------------------------------------------
    # Subroutines: 2. External Services & Queues
    # --------------------------------------------------------------------------

    def _discover_external_services(
        self,
        config_files: Optional[List[str]],
        service_nodes: List[RegistryNode],
        shard_path: Optional[str] = None,
    ) -> None:
        """Extracts external services, databases, caches, and queues from config files and env vars."""
        target_files = self._collect_files(
            config_files,
            [".env", ".env.example", ".yaml", ".yml", ".json", ".ini"],
            shard_path=shard_path,
        )

        service_patterns = {
            "postgres": re.compile(r"(?:POSTGRES|DATABASE_URL.*postgres)", re.IGNORECASE),
            "mysql": re.compile(r"(?:MYSQL|DATABASE_URL.*mysql)", re.IGNORECASE),
            "mongodb": re.compile(r"(?:MONGO|MONGODB_URI)", re.IGNORECASE),
            "redis": re.compile(r"(?:REDIS_URL|REDIS_HOST|REDIS)", re.IGNORECASE),
            "kafka": re.compile(r"(?:KAFKA_BROKERS|KAFKA)", re.IGNORECASE),
            "rabbitmq": re.compile(r"(?:RABBITMQ|AMQP)", re.IGNORECASE),
            "stripe": re.compile(r"(?:STRIPE_API_KEY|STRIPE_SECRET)", re.IGNORECASE),
            "aws_s3": re.compile(r"(?:AWS_S3|S3_BUCKET)", re.IGNORECASE),
            "openai": re.compile(r"(?:OPENAI_API_KEY)", re.IGNORECASE),
        }

        seen_services: Set[str] = set()

        for file_path in target_files:
            rel_path = str(file_path.relative_to(self.repo_root)) if file_path.is_relative_to(self.repo_root) else str(file_path)
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            for idx, line in enumerate(content.splitlines(), start=1):
                for s_name, pattern in service_patterns.items():
                    if pattern.search(line) and s_name not in seen_services:
                        seen_services.add(s_name)
                        h = hashlib.sha256(f"service:{s_name}:{rel_path}".encode("utf-8")).hexdigest()
                        service_node = RegistryNode(
                            id=f"service:{s_name}",
                            name=s_name,
                            type=NodeType.SERVICE,
                            location=NodeLocation(
                                path=rel_path,
                                start_line=idx,
                                service_name=s_name,
                                signature=f"Service: {s_name}",
                            ),
                            hash=h,
                            metadata={"config_file": rel_path},
                        )
                        service_nodes.append(service_node)

    # --------------------------------------------------------------------------
    # Subroutines: 3. API Discovery & Linking (api_to_code)
    # --------------------------------------------------------------------------

    def _discover_apis_and_link(
        self,
        api_specs: Optional[List[str]],
        api_nodes: List[RegistryNode],
        api_to_code_edges: List[SystemEdge],
        unresolved_queue: List[UnresolvedSystemLink],
        seen_edge_keys: Set[str],
        shard_path: Optional[str] = None,
    ) -> None:
        """Extracts REST/gRPC endpoints and links to handler functions via registry lookup."""
        target_files = self._collect_files(api_specs, [".py", ".js", ".ts", ".json"], shard_path=shard_path)

        for file_path in target_files:
            rel_path = str(file_path.relative_to(self.repo_root)) if file_path.is_relative_to(self.repo_root) else str(file_path)
            ext = file_path.suffix.lower()

            if ext in (".py", ".pyi"):
                self._extract_python_apis(
                    file_path=file_path,
                    rel_path=rel_path,
                    api_nodes=api_nodes,
                    api_to_code_edges=api_to_code_edges,
                    unresolved_queue=unresolved_queue,
                    seen_edge_keys=seen_edge_keys,
                )

    def _extract_python_apis(
        self,
        file_path: Path,
        rel_path: str,
        api_nodes: List[RegistryNode],
        api_to_code_edges: List[SystemEdge],
        unresolved_queue: List[UnresolvedSystemLink],
        seen_edge_keys: Set[str],
    ) -> None:
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(content, filename=rel_path)
        except Exception:
            return

        for item in ast.walk(tree):
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fn_name = item.name
                for dec in item.decorator_list:
                    route_info = self._extract_route_from_decorator(dec)
                    if not route_info:
                        continue

                    method, route = route_info
                    api_id = f"api:{method}:{route}"
                    h = hashlib.sha256(f"{api_id}:{rel_path}".encode("utf-8")).hexdigest()

                    api_node = RegistryNode(
                        id=api_id,
                        name=f"{method} {route}",
                        type=NodeType.API,
                        location=NodeLocation(
                            path=rel_path,
                            start_line=item.lineno,
                            endpoint_method=method,
                            endpoint_route=route,
                            signature=f"{method} {route} -> {fn_name}",
                        ),
                        hash=h,
                        metadata={"handler": fn_name, "framework": "web_framework"},
                    )
                    api_nodes.append(api_node)

                    # Look up handler function in registry before linking
                    handler_node_id = f"func:{rel_path}:{fn_name}"
                    handler_node = self.lookup_tool.get(handler_node_id)
                    if not handler_node:
                        # Try to find by name in file
                        file_nodes = self.lookup_tool.get_by_path(rel_path)
                        for n in file_nodes:
                            if n.name == fn_name or n.name.endswith(f".{fn_name}"):
                                handler_node = n
                                break

                    if handler_node:
                        edge_key = f"api_to_code:{api_node.id}->{handler_node.id}"
                        if edge_key not in seen_edge_keys:
                            seen_edge_keys.add(edge_key)
                            edge = SystemEdge.create(
                                source_id=api_node.id,
                                target_id=handler_node.id,
                                edge_type=SystemEdgeType.API_TO_CODE,
                                operation=method,
                                line_number=item.lineno,
                                metadata={"route": route, "handler": fn_name},
                            )
                            api_to_code_edges.append(edge)
                    else:
                        # Missing handler endpoint: never guess!
                        unresolved_queue.append(
                            UnresolvedSystemLink(
                                source_id=api_node.id,
                                source_path=rel_path,
                                raw_target=fn_name,
                                edge_type=SystemEdgeType.API_TO_CODE,
                                line_number=item.lineno,
                                reason=f"Handler function '{fn_name}' for endpoint '{method} {route}' not found in registry",
                            )
                        )

    def _extract_route_from_decorator(self, dec: ast.AST) -> Optional[Tuple[str, str]]:
        """Extracts (HTTP_METHOD, route_path) from common web framework decorators."""
        if not isinstance(dec, ast.Call):
            return None

        method = "GET"
        route = ""

        # Pattern 1: @app.get('/route') or @router.post('/route')
        if isinstance(dec.func, ast.Attribute):
            attr = dec.func.attr.upper()
            if attr in ("GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"):
                method = attr
                if dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str):
                    route = dec.args[0].value
            elif attr == "ROUTE":
                if dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str):
                    route = dec.args[0].value
                # Check methods keyword arg (e.g. methods=['POST'])
                for kw in dec.keywords:
                    if kw.arg in ("method", "methods"):
                        if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                            method = kw.value.value.upper()
                        elif isinstance(kw.value, ast.List) and kw.value.elts:
                            first = kw.value.elts[0]
                            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                                method = first.value.upper()

        # Pattern 2: @route('/route') (Bottle) or @get('/route')
        elif isinstance(dec.func, ast.Name):
            name = dec.func.id.upper()
            if name in ("GET", "POST", "PUT", "DELETE", "PATCH"):
                method = name
                if dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str):
                    route = dec.args[0].value
            elif name == "ROUTE":
                if dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str):
                    route = dec.args[0].value

        if route:
            return method, route
        return None

    # --------------------------------------------------------------------------
    # Subroutines: 4. SQL Queries & Table Access (code_to_table)
    # --------------------------------------------------------------------------

    def _discover_queries_and_link(
        self,
        query_code: Optional[List[str]],
        known_tables: Dict[str, RegistryNode],
        code_to_table_edges: List[SystemEdge],
        unresolved_queue: List[UnresolvedSystemLink],
        seen_edge_keys: Set[str],
        shard_path: Optional[str] = None,
    ) -> None:
        """Finds SQL query strings in code and links caller functions to registered database tables."""
        target_files = self._collect_files(query_code, [".py", ".js", ".ts"], shard_path=shard_path)

        query_pattern = re.compile(
            r"""\b(SELECT\s+.*?\s+FROM|INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+[`"']?([a-zA-Z0-9_]+)[`"']?""",
            re.IGNORECASE,
        )

        for file_path in target_files:
            rel_path = str(file_path.relative_to(self.repo_root)) if file_path.is_relative_to(self.repo_root) else str(file_path)
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            for idx, line in enumerate(content.splitlines(), start=1):
                match = query_pattern.search(line)
                if match:
                    op_raw = match.group(1).upper()
                    operation = "SELECT" if "SELECT" in op_raw else ("INSERT" if "INSERT" in op_raw else ("UPDATE" if "UPDATE" in op_raw else "DELETE"))
                    target_table_name = match.group(2).lower()

                    # Find caller function in registry
                    caller_node = self._find_caller_at_line(rel_path, idx)
                    source_id = caller_node.id if caller_node else f"file:{rel_path}"

                    # Strict registry lookup: check if table is registered
                    table_node = known_tables.get(target_table_name) or self.lookup_tool.get(f"table:{target_table_name}")

                    if table_node:
                        edge_key = f"code_to_table:{source_id}->{table_node.id}:{operation}"
                        if edge_key not in seen_edge_keys:
                            seen_edge_keys.add(edge_key)
                            edge = SystemEdge.create(
                                source_id=source_id,
                                target_id=table_node.id,
                                edge_type=SystemEdgeType.CODE_TO_TABLE,
                                operation=operation,
                                line_number=idx,
                                metadata={"table": target_table_name, "operation": operation},
                            )
                            code_to_table_edges.append(edge)
                    else:
                        # Table not in registry: route to unresolved queue, never guess!
                        unresolved_queue.append(
                            UnresolvedSystemLink(
                                source_id=source_id,
                                source_path=rel_path,
                                raw_target=target_table_name,
                                edge_type=SystemEdgeType.CODE_TO_TABLE,
                                line_number=idx,
                                reason=f"Referenced database table '{target_table_name}' not registered in schema or migrations",
                            )
                        )

    # --------------------------------------------------------------------------
    # Subroutines: 5. Cross-Service Calls (service_to_service)
    # --------------------------------------------------------------------------

    def _discover_cross_service_calls(
        self,
        known_services: Dict[str, RegistryNode],
        service_to_service_edges: List[SystemEdge],
        unresolved_queue: List[UnresolvedSystemLink],
        seen_edge_keys: Set[str],
        shard_path: Optional[str] = None,
    ) -> None:
        """Finds external service invocations (Stripe, Redis, S3, Kafka) and links to service nodes."""
        client_invocations = {
            "stripe": re.compile(r"\b(?:stripe\.|api\.stripe\.com)", re.IGNORECASE),
            "redis": re.compile(r"\b(?:redis_client|StrictRedis|redis\.Redis)", re.IGNORECASE),
            "kafka": re.compile(r"\b(?:KafkaProducer|KafkaConsumer|kafka\.)", re.IGNORECASE),
            "aws_s3": re.compile(r"\b(?:s3_client|boto3\.client\(['\"]s3)", re.IGNORECASE),
            "openai": re.compile(r"\b(?:openai\.ChatCompletion|OpenAI\()", re.IGNORECASE),
        }

        target_files = self._collect_files(None, [".py", ".js", ".ts"], shard_path=shard_path)

        for file_path in target_files:
            rel_path = str(file_path.relative_to(self.repo_root)) if file_path.is_relative_to(self.repo_root) else str(file_path)
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            for idx, line in enumerate(content.splitlines(), start=1):
                for s_name, pattern in client_invocations.items():
                    if pattern.search(line):
                        caller_node = self._find_caller_at_line(rel_path, idx)
                        source_id = caller_node.id if caller_node else f"file:{rel_path}"

                        # Check if target service exists in registry
                        service_node = known_services.get(s_name) or self.lookup_tool.get(f"service:{s_name}")

                        if service_node:
                            edge_key = f"service_to_service:{source_id}->{service_node.id}"
                            if edge_key not in seen_edge_keys:
                                seen_edge_keys.add(edge_key)
                                edge = SystemEdge.create(
                                    source_id=source_id,
                                    target_id=service_node.id,
                                    edge_type=SystemEdgeType.SERVICE_TO_SERVICE,
                                    line_number=idx,
                                    metadata={"service": s_name},
                                )
                                service_to_service_edges.append(edge)
                        else:
                            unresolved_queue.append(
                                UnresolvedSystemLink(
                                    source_id=source_id,
                                    source_path=rel_path,
                                    raw_target=s_name,
                                    edge_type=SystemEdgeType.SERVICE_TO_SERVICE,
                                    line_number=idx,
                                    reason=f"External service '{s_name}' is referenced in code but not configured/registered as a system service",
                                )
                            )

    # --------------------------------------------------------------------------
    # Helpers
    # --------------------------------------------------------------------------

    def _collect_files(
        self,
        explicit_paths: Optional[List[str]],
        extensions: List[str],
        shard_path: Optional[str] = None,
    ) -> List[Path]:
        """Collects real files matching extensions from explicit paths or repository walk."""
        matched: List[Path] = []
        if explicit_paths:
            for ep in explicit_paths:
                p = (self.repo_root / ep).resolve()
                if p.is_file():
                    matched.append(p)
                elif p.is_dir():
                    for root, _, files in os.walk(p):
                        for f in files:
                            if any(f.endswith(ext) for ext in extensions):
                                matched.append(Path(root) / f)
            return matched

        scan_root = (self.repo_root / shard_path).resolve() if shard_path else self.repo_root
        if not scan_root.exists():
            return []

        excluded = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "node_modules", ".registry", "dist", "build"}
        for root, dirs, files in os.walk(scan_root):
            dirs[:] = [d for d in dirs if d not in excluded and not d.startswith(".")]
            for f in files:
                if any(f.endswith(ext) for ext in extensions):
                    matched.append(Path(root) / f)

        return sorted(matched)

    def _find_caller_at_line(self, rel_path: str, line_number: int) -> Optional[RegistryNode]:
        """Finds the most specific active function or class node enclosing the given line number."""
        file_nodes = self.lookup_tool.get_by_path(rel_path)
        enclosing_node: Optional[RegistryNode] = None

        for node in file_nodes:
            if node.type in (NodeType.FUNCTION, NodeType.CLASS):
                start = node.location.start_line
                end = node.location.end_line
                if start and end and start <= line_number <= end:
                    enclosing_node = node
                    if node.type == NodeType.FUNCTION:
                        return node  # Prefer function level

        return enclosing_node
