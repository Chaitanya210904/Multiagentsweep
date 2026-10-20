"""
Structure Mapper Agent
Layer: graph
Role: Graph agent 1: nodes
Description: Walks one shard at a time and creates a node for every file, class and function.
             Registers each node before it is used anywhere.
Access: read-only
Model Tier: small
Trigger: after Registry Keeper; per changed shard
"""

from datetime import datetime, timezone
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from agents.base import AgentMetadata, BaseAgent
from models.registry import (
    NodeType,
    RegistryKeeperInput,
    RegistryKeeperOutput,
    RegistryNode,
    UpdateProposal,
)
from models.structure import (
    DEFAULT_LANGUAGE_CONFIGS,
    LanguageConfig,
    RepoShard,
    StructureMapperInput,
    StructureMapperOutput,
)
from storage.registry_store import CodeRegistryStore
from tools.registry_lookup_tool import RegistryLookupTool
from tools.registry_propose_tool import RegistryProposeTool
from tools.scip_tool import ScipTool
from tools.tree_sitter_tool import TreeSitterTool

logger = logging.getLogger(__name__)


STRUCTURE_MAPPER_METADATA = AgentMetadata(
    id="structure_mapper",
    name="Structure Mapper",
    layer="graph",
    role="Graph agent 1: nodes",
    description=(
        "Walks one shard at a time and creates a node for every file, class and function. "
        "Registers each node before it is used anywhere."
    ),
    access="read-only",
    model_tier="small",
    inputs=[
        "repo_shard",
        "language_configs",
        "registry",
    ],
    outputs=[
        "nodes(id,type,path,signature,hash,summary)",
        "registry_update_proposals",
    ],
    tools=[
        "tree_sitter",
        "scip",
        "registry.lookup",
        "registry.propose",
    ],
    trigger="after Registry Keeper; per changed shard",
    optional=False,
)


class StructureMapper(BaseAgent):
    """
    Graph Agent 1: Structure Mapper.
    Walks repository shards and extracts structural code nodes (file, class, function).
    Packages proposals for Registry Keeper so each node is registered before being used anywhere.
    """

    def __init__(
        self,
        store: Optional[CodeRegistryStore] = None,
        repo_root: Optional[str] = None,
        metadata: Optional[AgentMetadata] = None,
    ):
        super().__init__(metadata=metadata or STRUCTURE_MAPPER_METADATA)
        self.repo_root = Path(repo_root).resolve() if repo_root else Path.cwd().resolve()
        self.store = store or CodeRegistryStore(persistence_path=":memory:")

        # Tools
        self.tree_sitter_tool = TreeSitterTool(repo_root=str(self.repo_root))
        self.scip_tool = ScipTool(package_name="multiagent")
        self.lookup_tool = RegistryLookupTool(store=self.store)
        self.propose_tool = RegistryProposeTool(source_agent=self.id)

    def execute(self, inputs: StructureMapperInput) -> StructureMapperOutput:
        """
        Executes shard mapping:
        1. Resolves shard files
        2. Parses code entities (files, classes, functions) with Tree-sitter / AST
        3. Enriches nodes with SCIP code intelligence symbols
        4. Cross-checks existing nodes in the registry using registry.lookup
        5. Generates formal registry update proposals using registry.propose
        """
        # Enforce read-only constraint
        self.require_access("read-only")

        # 1. Resolve Shard
        shard = self._resolve_shard(inputs.repo_shard)
        lang_configs = inputs.language_configs or DEFAULT_LANGUAGE_CONFIGS

        # 2. Collect target files
        files_to_scan = self._get_shard_files(shard, lang_configs)

        # 3. Extract nodes using tree_sitter tool
        all_nodes: List[RegistryNode] = []
        for file_path in files_to_scan:
            extracted = self.tree_sitter_tool.parse_file(file_path)
            # 4. Enrich with SCIP symbols
            enriched = self.scip_tool.enrich_nodes(extracted)
            all_nodes.extend(enriched)

        # 5. Build proposals using registry.propose
        proposals = self.propose_tool.build_proposals(
            nodes=all_nodes,
            lookup_tool=self.lookup_tool,
            only_changed=inputs.only_changed,
        )

        stats = {
            "shard_id": shard.shard_id,
            "root_path": shard.root_path,
            "files_scanned": len(files_to_scan),
            "total_nodes_extracted": len(all_nodes),
            "proposals_generated": len(proposals),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        return StructureMapperOutput(
            shard_id=shard.shard_id,
            nodes=all_nodes,
            registry_update_proposals=proposals,
            stats=stats,
        )

    def map_and_register(
        self,
        registry_keeper: Any,
        repo_shard: Union[RepoShard, str],
        only_changed: bool = False,
    ) -> Tuple[StructureMapperOutput, RegistryKeeperOutput]:
        """
        End-to-end integration pipeline:
        Maps the shard into nodes, generates proposals, and registers them
        with the Registry Keeper before the nodes are used anywhere else.
        """
        mapper_inputs = StructureMapperInput(repo_shard=repo_shard, only_changed=only_changed)
        mapper_output = self.execute(mapper_inputs)

        # Pass proposals directly to the Registry Keeper
        keeper_inputs = RegistryKeeperInput(
            update_proposals_from_structure_mapper=mapper_output.registry_update_proposals
        )
        keeper_output = registry_keeper.execute(keeper_inputs)

        return mapper_output, keeper_output

    # --------------------------------------------------------------------------
    # Helpers
    # --------------------------------------------------------------------------

    def _resolve_shard(self, shard_input: Union[RepoShard, str]) -> RepoShard:
        """Converts string directory path or RepoShard instance to canonical RepoShard."""
        if isinstance(shard_input, RepoShard):
            return shard_input
        return RepoShard.from_directory(shard_input, repo_root=self.repo_root)

    def _get_shard_files(self, shard: RepoShard, lang_configs: Dict[str, LanguageConfig]) -> List[Path]:
        """Identifies all source files within the shard matching configured language extensions."""
        shard_dir = (self.repo_root / shard.root_path).resolve()
        if not shard_dir.exists():
            return []

        # If explicit files list provided
        if shard.files is not None:
            return [(self.repo_root / f).resolve() for f in shard.files if (self.repo_root / f).is_file()]

        # If shard points directly to a single file
        if shard_dir.is_file():
            return [shard_dir]

        # Collect configured extensions
        valid_extensions: Set[str] = set()
        for cfg in lang_configs.values():
            valid_extensions.update(ext.lower() for ext in cfg.extensions)

        excluded = {
            ".git",
            ".venv",
            "venv",
            "__pycache__",
            ".pytest_cache",
            "node_modules",
            ".registry",
            "dist",
            "build",
            ".egg-info",
        }

        matched_files: List[Path] = []
        for root, dirs, files in os.walk(shard_dir):
            dirs[:] = [d for d in dirs if d not in excluded and not d.startswith(".")]
            for file_name in files:
                if file_name.startswith("."):
                    continue
                p = Path(root) / file_name
                # Check extension
                if not valid_extensions or p.suffix.lower() in valid_extensions:
                    matched_files.append(p)

        return sorted(matched_files)
