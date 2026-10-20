"""
Tool: registry.propose
Enables read-only agents like Structure Mapper to package validated code nodes
into structured UpdateProposal objects destined for the Registry Keeper.
"""

from typing import Any, Dict, List, Optional
import uuid

from models.registry import ChangeAction, RegistryNode, UpdateProposal
from tools.registry_lookup_tool import RegistryLookupTool


class RegistryProposeTool:
    """Tool for packaging code nodes into formal UpdateProposal payloads."""

    name = "registry.propose"
    description = "Packages code nodes into structured UpdateProposal objects for Registry Keeper."

    def __init__(self, source_agent: str = "structure_mapper"):
        self.source_agent = source_agent

    def propose_create(self, node: RegistryNode, details: Optional[Dict[str, Any]] = None) -> UpdateProposal:
        """Formulate a creation proposal for a new node."""
        return UpdateProposal(
            proposal_id=str(uuid.uuid4()),
            source_agent=self.source_agent,
            action=ChangeAction.CREATE,
            node=node,
            details=details or {"action": "create_node", "name": node.name},
        )

    def propose_update(self, node: RegistryNode, details: Optional[Dict[str, Any]] = None) -> UpdateProposal:
        """Formulate an update proposal for an existing modified node."""
        return UpdateProposal(
            proposal_id=str(uuid.uuid4()),
            source_agent=self.source_agent,
            action=ChangeAction.UPDATE,
            node=node,
            details=details or {"action": "update_node", "name": node.name},
        )

    def build_proposals(
        self,
        nodes: List[RegistryNode],
        lookup_tool: Optional[RegistryLookupTool] = None,
        only_changed: bool = False,
    ) -> List[UpdateProposal]:
        """
        Takes a list of extracted code nodes and checks them against the registry:
        - If node does not exist -> creates CREATE proposal.
        - If node exists with changed hash -> creates UPDATE proposal.
        - If node exists with unchanged hash -> skips if only_changed=True, or creates CREATE/UPDATE proposal.
        """
        proposals: List[UpdateProposal] = []

        for node in nodes:
            if lookup_tool:
                existing = lookup_tool.get(node.id)
                if not existing:
                    proposals.append(self.propose_create(node, details={"status": "new_node"}))
                elif existing.hash != node.hash:
                    proposals.append(self.propose_update(node, details={"status": "modified_hash", "old_hash": existing.hash}))
                elif not only_changed:
                    # Unchanged, but re-registering
                    proposals.append(self.propose_create(node, details={"status": "unchanged"}))
            else:
                proposals.append(self.propose_create(node))

        return proposals
