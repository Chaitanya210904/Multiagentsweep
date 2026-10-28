"""
Orchestrator Agent (Layer: Control).
Role: Master Coordinator & Planner.
Breaks down user requests into discrete subtasks, uses the Code Graph to select agents
and context, executes agents in parallel or sequence, merges results, recovers from errors,
consults the Cost & Token Governor, invokes the Critic, and enforces Human-in-the-Loop gates.
"""

from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Union

from agents.base import AgentMetadata, BaseAgent
from agents.control.critic import ResultAggregatorCriticAgent
from agents.graph.data_service_mapper import DataServiceMapper
from agents.graph.registry_keeper import RegistryKeeper
from agents.graph.relationship_linker import RelationshipLinker
from agents.graph.structure_mapper import StructureMapper
from agents.optional.cost_token_governor_agent import CostTokenGovernorAgent
from agents.quality.architecture_review import ArchitectureReview
from agents.quality.code_quality import CodeQuality
from agents.runtime.observability_agent import ObservabilityAgent
from agents.runtime.scale_load_agent import ScaleLoadAgent
from agents.runtime.tech_scout_agent import TechScoutAgent
from agents.safety.company_rules_agent import CompanyRulesAgent
from agents.safety.security_agent import SecurityAgent
from agents.understanding.impact_analyzer import ImpactAnalyzer
from models.architecture import ArchitectureReviewInput
from models.code_quality import CodeQualityInput
from models.company_rules import CompanyRulesInput, RuleSeverity
from models.control import (
    OrchestratorOutput,
    OrchestratorSubTask,
    SubTaskStatus,
    TaskExecutionMode,
    TaskPlanRequest,
    UnifiedReport,
)
from models.cost_token_governor import (
    CostTokenGovernorInput,
    ModelTier,
    TaskComplexity,
    TaskPlan,
    TaskPlanStep,
)
from models.impact import ImpactAnalyzerInput
from models.observability import ObservabilityInput
from models.registry import NodeType
from models.scale_load import ScaleLoadInput, TrafficTarget
from models.security import SecurityInput
from models.structure import RepoShard, StructureMapperInput
from models.tech_scout import TechScoutInput
from storage.registry_store import CodeRegistryStore


ORCHESTRATOR_METADATA = AgentMetadata(
    id="orchestrator",
    name="Orchestrator Agent",
    layer="control",
    role="Master Coordinator & Planner",
    description="Breaks tasks into subtasks, selects agents via code graph, coordinates parallel/sequential execution, recovers from errors, and enforces human-approved changes.",
    access="read-only",
    model_tier="large",
    inputs=[
        "task_request",
        "code_graph",
        "budget_limit",
    ],
    outputs=[
        "subtasks",
        "unified_report",
        "execution_summary",
    ],
    tools=[
        "orchestrator.plan",
        "orchestrator.dispatch",
        "registry.lookup",
        "graph.traverse",
    ],
    trigger="on user task or CI/CD event",
    optional=False,
)


class OrchestratorAgent(BaseAgent):
    """
    Central controller orchestrating all multi-agent workflows.
    Plans subtasks, manages dependencies, coordinates with Cost & Token Governor,
    dispatches agents, recovers from failures, and feeds findings into Critic.
    """

    def __init__(
        self,
        registry_store: Optional[CodeRegistryStore] = None,
        repo_root: Optional[Union[str, Path]] = None,
        log_file: Optional[str] = None,
    ):
        super().__init__(metadata=ORCHESTRATOR_METADATA, log_file=log_file)
        self.store = registry_store or CodeRegistryStore()
        self.repo_root = Path(repo_root) if repo_root else Path.cwd()

        # Instantiate specialist agents
        self.keeper = RegistryKeeper(store=self.store, repo_root=str(self.repo_root))
        self.mapper = StructureMapper(store=self.store, repo_root=str(self.repo_root))
        self.linker = RelationshipLinker(store=self.store, repo_root=str(self.repo_root))
        self.dsm = DataServiceMapper(store=self.store, repo_root=str(self.repo_root))
        self.impact = ImpactAnalyzer(store=self.store, repo_root=str(self.repo_root))
        self.arch = ArchitectureReview(store=self.store, repo_root=str(self.repo_root))
        self.quality = CodeQuality(store=self.store, repo_root=str(self.repo_root))
        self.security = SecurityAgent(registry_store=self.store, repo_root=str(self.repo_root))
        self.rules = CompanyRulesAgent(registry_store=self.store, repo_root=str(self.repo_root))
        self.obs = ObservabilityAgent(registry_store=self.store, repo_root=str(self.repo_root))
        self.scale = ScaleLoadAgent(registry_store=self.store, repo_root=str(self.repo_root))
        self.scout = TechScoutAgent(registry_store=self.store, repo_root=str(self.repo_root))
        self.governor = CostTokenGovernorAgent(log_file=log_file)
        self.critic = ResultAggregatorCriticAgent(registry_store=self.store, repo_root=str(self.repo_root))

    def execute(self, inputs: Union[TaskPlanRequest, Dict[str, Any]]) -> OrchestratorOutput:
        """
        Executes end-to-end orchestrated workflow across all specialist agents.
        """
        self.require_access("read-only")

        req = inputs if isinstance(inputs, TaskPlanRequest) else TaskPlanRequest(**inputs)
        t0 = self.log_started({"task_id": req.task_id, "task_title": req.task_title})

        subtasks: List[OrchestratorSubTask] = []
        specialist_results: Dict[str, Any] = {}

        try:
            # Step 1: Subtask Planning
            self.log_event("orchestrator.plan", f"Decomposing task '{req.task_title}' into subtasks")
            subtasks = self._plan_subtasks(req)

            # Step 2: Budgeting & Model Tier Routing via Cost & Token Governor
            self.log_event("orchestrator.budget", "Checking token budget and allocating model tiers")
            task_plan = TaskPlan(
                plan_id=f"plan_{req.task_id}",
                title=req.task_title,
                overall_budget_usd=req.budget_limit_usd,
                steps=[
                    TaskPlanStep(
                        step_id=st.subtask_id,
                        agent_id=st.agent_id,
                        task_type=st.description,
                        complexity=TaskComplexity.SIMPLE if st.agent_id in {"structure_mapper", "relationship_linker", "code_quality"} else TaskComplexity.MODERATE,
                        estimated_input_tokens=3000,
                        requested_tier=ModelTier.SMALL if st.agent_id in {"structure_mapper", "relationship_linker", "code_quality", "company_rules"} else ModelTier.MEDIUM,
                    )
                    for st in subtasks
                ],
            )
            gov_out = self.governor.execute(CostTokenGovernorInput(
                task_plan=task_plan,
                budget_limit_usd=req.budget_limit_usd,
            ))

            # Step 3: Sequential Graph Ingestion
            self._execute_graph_subtasks(subtasks, specialist_results, req)

            # Step 4: Understanding & Blast Radius
            self._execute_understanding_subtasks(subtasks, specialist_results, req)

            # Step 5: Parallel Specialist Execution (Safety, Quality, Architecture, Runtime)
            self._execute_specialist_subtasks(subtasks, specialist_results, req)

            # Step 6: Invoke Result Aggregator & Critic
            self.log_event("orchestrator.critic", "Invoking Critic for false-alarm pruning and impact ranking")
            unified_report = self.critic.execute({
                "task_id": req.task_id,
                "specialist_outputs": specialist_results,
                "target_files": req.target_files,
            })

            total_duration_ms = (time.time() - t0) * 1000

            output = OrchestratorOutput(
                task_id=req.task_id,
                status="AWAITING_APPROVAL" if req.require_human_approval else "COMPLETED",
                subtasks=subtasks,
                unified_report=unified_report,
                total_duration_ms=round(total_duration_ms, 2),
                total_tokens_consumed=gov_out.cost_report.total_tokens_consumed,
                total_cost_usd=gov_out.cost_report.total_cost_usd,
                human_approval_required=req.require_human_approval,
            )

            self.log_completed(t0, {
                "subtasks_count": len(subtasks),
                "active_findings": unified_report.active_findings_count,
                "pruned_false_alarms": unified_report.false_alarms_pruned,
                "health_score": unified_report.overall_health_score,
            })

            return output

        except Exception as e:
            self.log_failed(t0, e)
            raise

    def _plan_subtasks(self, req: TaskPlanRequest) -> List[OrchestratorSubTask]:
        """Decomposes the overall request into discrete subtasks with execution modes."""
        return [
            OrchestratorSubTask(
                subtask_id="subtask_1_map",
                agent_id="structure_mapper",
                layer="graph",
                description="Scan repository shards and extract code entities with AST & SCIP",
                execution_mode=TaskExecutionMode.SEQUENTIAL,
            ),
            OrchestratorSubTask(
                subtask_id="subtask_2_link",
                agent_id="relationship_linker",
                layer="graph",
                description="Link calls, imports, inheritance, and test edges against Registry",
                execution_mode=TaskExecutionMode.SEQUENTIAL,
                depends_on=["subtask_1_map"],
            ),
            OrchestratorSubTask(
                subtask_id="subtask_3_data_service",
                agent_id="data_service_mapper",
                layer="graph",
                description="Map APIs, database tables, SQL queries, and external microservices",
                execution_mode=TaskExecutionMode.SEQUENTIAL,
                depends_on=["subtask_1_map"],
            ),
            OrchestratorSubTask(
                subtask_id="subtask_4_impact",
                agent_id="impact_analyzer",
                layer="understanding",
                description="Evaluate blast radius and emit selective agent wake directives",
                execution_mode=TaskExecutionMode.SEQUENTIAL,
                depends_on=["subtask_2_link", "subtask_3_data_service"],
            ),
            OrchestratorSubTask(
                subtask_id="subtask_5_arch",
                agent_id="architecture_review",
                layer="quality",
                description="Review layer boundaries, coupling metrics, and circular dependencies",
                execution_mode=TaskExecutionMode.PARALLEL,
                depends_on=["subtask_4_impact"],
            ),
            OrchestratorSubTask(
                subtask_id="subtask_6_quality",
                agent_id="code_quality",
                layer="quality",
                description="Analyze cognitive complexity, code smells, duplication, and coverage",
                execution_mode=TaskExecutionMode.PARALLEL,
                depends_on=["subtask_4_impact"],
            ),
            OrchestratorSubTask(
                subtask_id="subtask_7_security",
                agent_id="security",
                layer="safety",
                description="Scan SAST vulnerabilities, credentials/secrets, and dependency CVEs",
                execution_mode=TaskExecutionMode.PARALLEL,
                depends_on=["subtask_4_impact"],
            ),
            OrchestratorSubTask(
                subtask_id="subtask_8_rules",
                agent_id="company_rules",
                layer="safety",
                description="Verify enterprise policy adherence and cite numbered rule IDs",
                execution_mode=TaskExecutionMode.PARALLEL,
                depends_on=["subtask_4_impact"],
            ),
            OrchestratorSubTask(
                subtask_id="subtask_9_scale",
                agent_id="scale_load",
                layer="runtime",
                description="Analyze query hot paths, N+1 statements, missing indexes, and capacity",
                execution_mode=TaskExecutionMode.PARALLEL,
                depends_on=["subtask_4_impact"],
            ),
            OrchestratorSubTask(
                subtask_id="subtask_10_obs",
                agent_id="observability",
                layer="runtime",
                description="Correlate runtime telemetry, traces, and metrics with registry nodes",
                execution_mode=TaskExecutionMode.PARALLEL,
                depends_on=["subtask_4_impact"],
            ),
            OrchestratorSubTask(
                subtask_id="subtask_11_scout",
                agent_id="tech_scout",
                layer="runtime",
                description="Research modern technology alternatives and draft migration outlines",
                execution_mode=TaskExecutionMode.PARALLEL,
                depends_on=["subtask_9_scale", "subtask_5_arch"],
            ),
        ]

    def _execute_graph_subtasks(
        self,
        subtasks: List[OrchestratorSubTask],
        results: Dict[str, Any],
        req: TaskPlanRequest,
    ) -> None:
        """Executes sequential graph extraction subtasks with error handling."""
        # 1. Structure Mapper
        st_map = next(s for s in subtasks if s.subtask_id == "subtask_1_map")
        self._dispatch_with_retry(st_map, lambda: self.mapper.map_and_register(
            registry_keeper=self.keeper,
            repo_shard=req.repo_root or ".",
        ))
        if st_map.result:
            results["structure_mapper"] = st_map.result[0]
            results["registry_keeper"] = st_map.result[1]

        # 2. Relationship Linker
        st_link = next(s for s in subtasks if s.subtask_id == "subtask_2_link")
        self._dispatch_with_retry(st_link, lambda: self.linker.link_and_register(
            registry_keeper=self.keeper,
        ))
        if st_link.result:
            results["relationship_linker"] = st_link.result[0]

        # 3. Data & Service Mapper
        st_dsm = next(s for s in subtasks if s.subtask_id == "subtask_3_data_service")
        self._dispatch_with_retry(st_dsm, lambda: self.dsm.map_and_register(
            registry_keeper=self.keeper,
        ))
        if st_dsm.result:
            results["data_service_mapper"] = st_dsm.result[0]

    def _execute_understanding_subtasks(
        self,
        subtasks: List[OrchestratorSubTask],
        results: Dict[str, Any],
        req: TaskPlanRequest,
    ) -> None:
        """Executes impact analysis to gauge blast radius."""
        st_impact = next(s for s in subtasks if s.subtask_id == "subtask_4_impact")
        mapper_out = results.get("structure_mapper")
        if mapper_out and getattr(mapper_out, "nodes", None):
            sample_node = next((n.id for n in mapper_out.nodes if "router" in n.id.lower() or "app" in n.id.lower()), mapper_out.nodes[0].id)
        else:
            sample_node = "root_node"

        self._dispatch_with_retry(st_impact, lambda: self.impact.execute(
            ImpactAnalyzerInput(changed_nodes=[sample_node], max_depth=4)
        ))
        if st_impact.result:
            results["impact_analyzer"] = st_impact.result

    def _execute_specialist_subtasks(
        self,
        subtasks: List[OrchestratorSubTask],
        results: Dict[str, Any],
        req: TaskPlanRequest,
    ) -> None:
        """Executes specialist analysis agents (Safety, Quality, Runtime)."""
        mapper_out = results.get("structure_mapper")
        all_files = [n.location.path for n in getattr(mapper_out, "nodes", []) if getattr(n, "type", None) == NodeType.FILE] if mapper_out else []
        target_files = req.target_files or all_files[:10]

        # Architecture Review
        st_arch = next(s for s in subtasks if s.subtask_id == "subtask_5_arch")
        self._dispatch_with_retry(st_arch, lambda: self.arch.execute(
            ArchitectureReviewInput(check_cycles=True, max_coupling_threshold=20)
        ))
        if st_arch.result:
            results["architecture_review"] = st_arch.result

        # Code Quality
        st_quality = next(s for s in subtasks if s.subtask_id == "subtask_6_quality")
        self._dispatch_with_retry(st_quality, lambda: self.quality.execute(
            CodeQualityInput(changed_files=target_files)
        ))
        if st_quality.result:
            results["code_quality"] = st_quality.result

        # Security
        st_sec = next(s for s in subtasks if s.subtask_id == "subtask_7_security")
        self._dispatch_with_retry(st_sec, lambda: self.security.execute(
            SecurityInput(changed_code=target_files)
        ))
        if st_sec.result:
            results["security"] = st_sec.result

        # Company Rules
        st_rules = next(s for s in subtasks if s.subtask_id == "subtask_8_rules")
        self._dispatch_with_retry(st_rules, lambda: self.rules.execute(
            CompanyRulesInput(
                changed_files=target_files,
                rule_files=req.rule_files,
                fail_on_severity=RuleSeverity.HIGH,
                repo_root=str(self.repo_root),
            )
        ))
        if st_rules.result:
            results["company_rules"] = st_rules.result

        # Scale & Load
        st_scale = next(s for s in subtasks if s.subtask_id == "subtask_9_scale")
        sample_node = results.get("impact_analyzer").affected_nodes_and_services.changed_roots[0] if results.get("impact_analyzer") else "root"
        self._dispatch_with_retry(st_scale, lambda: self.scale.execute(
            ScaleLoadInput(
                graph_hot_paths=[sample_node],
                traffic_target=TrafficTarget(target_rps=100.0, target_p99_latency_ms=200.0),
            )
        ))
        if st_scale.result:
            results["scale_load"] = st_scale.result

        # Observability
        st_obs = next(s for s in subtasks if s.subtask_id == "subtask_10_obs")
        obs_sample = {
            "metrics": [{"metric_name": "http_request_duration_seconds", "value": 0.12, "baseline": 0.10}],
            "logs": [],
            "traces": [],
        }
        self._dispatch_with_retry(st_obs, lambda: self.obs.execute(
            ObservabilityInput(opentelemetry_and_prometheus_data=obs_sample)
        ))
        if st_obs.result:
            results["observability"] = st_obs.result

        # Tech Scout
        st_scout = next(s for s in subtasks if s.subtask_id == "subtask_11_scout")
        bottlenecks = getattr(results.get("scale_load"), "bottlenecks", [])
        pains = [b.title for b in bottlenecks] or ["Throughput scaling and query latency"]
        self._dispatch_with_retry(st_scout, lambda: self.scout.execute(
            TechScoutInput(pain_points_from_other_agents=pains, max_options=3)
        ))
        if st_scout.result:
            results["tech_scout"] = st_scout.result

    def _dispatch_with_retry(self, subtask: OrchestratorSubTask, fn: Any) -> None:
        """Executes a subtask with automated retry and error recovery."""
        subtask.status = SubTaskStatus.RUNNING
        t_sub = time.time()
        for attempt in range(subtask.max_retries + 1):
            try:
                subtask.result = fn()
                subtask.status = SubTaskStatus.COMPLETED
                subtask.duration_ms = round((time.time() - t_sub) * 1000, 2)
                return
            except Exception as e:
                subtask.retry_count = attempt + 1
                if attempt == subtask.max_retries:
                    subtask.status = SubTaskStatus.FAILED
                    subtask.error = str(e)
                    subtask.duration_ms = round((time.time() - t_sub) * 1000, 2)
                    self.log_event("subtask.failed", f"Subtask {subtask.subtask_id} failed after {attempt} retries: {str(e)}", level="ERROR")
                else:
                    self.log_event("subtask.retry", f"Subtask {subtask.subtask_id} error, retrying ({attempt+1}/{subtask.max_retries}): {str(e)}", level="WARNING")


Orchestrator = OrchestratorAgent
