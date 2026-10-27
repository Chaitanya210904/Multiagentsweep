"""
Tool: usage.read
Reads token consumption, telemetry, and API costs across all multi-agent operations.
Computes real-time and historical costs based on model tier pricing ($/1M tokens).
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from core.logger import AgentLogger
from models.cost_token_governor import AgentTokenUsage, ModelTier, TokenUsageSummary


class UsageReadTool:
    """
    Telemetry tool for tracking prompt tokens, completion tokens, and dollar expenditures.
    Reads from central agent event logs and telemetry records.
    """

    name = "usage.read"
    description = (
        "Reads token usage metrics from central agent logs and calculates "
        "accurate costs per agent and model tier based on live pricing rates."
    )

    # Standard model tier pricing per 1,000,000 tokens (USD)
    PRICING = {
        ModelTier.SMALL: {"input": 0.075, "output": 0.30},     # e.g., gemini-2.5-flash
        ModelTier.MEDIUM: {"input": 1.00, "output": 4.00},      # e.g., gemini-2.5-pro
        ModelTier.LARGE: {"input": 5.00, "output": 15.00},      # e.g., gemini-ultra / opus
    }

    def __init__(self, log_file: Optional[Union[str, Path]] = None):
        self.log_file = Path(log_file) if log_file else Path("logs/agents.jsonl")

    def calculate_cost(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        tier: Union[ModelTier, str] = ModelTier.SMALL,
    ) -> float:
        """Calculates USD cost for given token counts and model tier."""
        tier_enum = ModelTier(tier) if isinstance(tier, str) else tier
        rates = self.PRICING.get(tier_enum, self.PRICING[ModelTier.SMALL])
        cost = (prompt_tokens / 1_000_000.0) * rates["input"] + (completion_tokens / 1_000_000.0) * rates["output"]
        return round(cost, 6)

    def estimate_step_cost(
        self,
        estimated_input_tokens: int,
        estimated_output_tokens: int,
        tier: Union[ModelTier, str],
    ) -> float:
        """Estimates cost for an upcoming step before execution."""
        return self.calculate_cost(estimated_input_tokens, estimated_output_tokens, tier)

    def read_usage(
        self,
        raw_telemetry: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = None,
    ) -> TokenUsageSummary:
        """
        Ingests token usage metrics from explicit payload or scans the central log file.
        Aggregates prompt tokens, completion tokens, costs, and invocation counts by agent.
        """
        agent_usages: Dict[str, AgentTokenUsage] = {}
        tier_usage: Dict[str, int] = {
            ModelTier.SMALL.value: 0,
            ModelTier.MEDIUM.value: 0,
            ModelTier.LARGE.value: 0,
        }

        # 1. Ingest from explicit telemetry payload if supplied
        if raw_telemetry:
            self._ingest_explicit_telemetry(raw_telemetry, agent_usages, tier_usage)

        # 2. Ingest from central JSONL log file if present
        log_path = self.log_file if self.log_file.exists() else Path("logs/agents.jsonl")
        if log_path.exists():
            self._ingest_from_log_file(agent_usages, tier_usage, file_path=log_path)

        # 3. Aggregate totals
        total_prompt = sum(u.prompt_tokens for u in agent_usages.values())
        total_completion = sum(u.completion_tokens for u in agent_usages.values())
        total_tokens = total_prompt + total_completion
        total_cost = sum(u.estimated_cost_usd for u in agent_usages.values())

        return TokenUsageSummary(
            total_prompt_tokens=total_prompt,
            total_completion_tokens=total_completion,
            total_tokens=total_tokens,
            total_cost_usd=round(total_cost, 6),
            usage_by_agent=agent_usages,
            usage_by_tier=tier_usage,
        )

    def _ingest_explicit_telemetry(
        self,
        telemetry: Union[Dict[str, Any], List[Dict[str, Any]]],
        agent_usages: Dict[str, AgentTokenUsage],
        tier_usage: Dict[str, int],
    ) -> None:
        """Parses structured dictionary or list of telemetry records."""
        items = telemetry if isinstance(telemetry, list) else [telemetry]
        for it in items:
            if not isinstance(it, dict):
                continue

            # Support nested dict under "usage_by_agent" or direct agent usage record
            if "usage_by_agent" in it:
                for a_id, data in it["usage_by_agent"].items():
                    self._record_agent_usage(a_id, data, agent_usages, tier_usage)
            else:
                agent_id = it.get("agent_id") or it.get("agent") or "unknown_agent"
                self._record_agent_usage(agent_id, it, agent_usages, tier_usage)

    def _record_agent_usage(
        self,
        agent_id: str,
        data: Dict[str, Any],
        agent_usages: Dict[str, AgentTokenUsage],
        tier_usage: Dict[str, int],
    ) -> None:
        """Helper to accumulate usage data for an agent."""
        p_tokens = int(data.get("prompt_tokens") or data.get("input_tokens") or 0)
        c_tokens = int(data.get("completion_tokens") or data.get("output_tokens") or 0)
        tier_str = str(data.get("model_tier") or "small").lower()
        tier = ModelTier.SMALL if "small" in tier_str else (ModelTier.LARGE if "large" in tier_str else ModelTier.MEDIUM)

        cost = self.calculate_cost(p_tokens, c_tokens, tier)
        calls = int(data.get("calls_count") or data.get("calls") or 1)

        if agent_id not in agent_usages:
            agent_usages[agent_id] = AgentTokenUsage(
                agent_id=agent_id,
                prompt_tokens=p_tokens,
                completion_tokens=c_tokens,
                total_tokens=p_tokens + c_tokens,
                estimated_cost_usd=round(cost, 6),
                calls_count=calls,
            )
        else:
            cur = agent_usages[agent_id]
            cur.prompt_tokens += p_tokens
            cur.completion_tokens += c_tokens
            cur.total_tokens += (p_tokens + c_tokens)
            cur.estimated_cost_usd = round(cur.estimated_cost_usd + cost, 6)
            cur.calls_count += calls

        tier_usage[tier.value] = tier_usage.get(tier.value, 0) + (p_tokens + c_tokens)

    def _ingest_from_log_file(
        self,
        agent_usages: Dict[str, AgentTokenUsage],
        tier_usage: Dict[str, int],
        file_path: Optional[Path] = None,
    ) -> None:
        """Scans agents.jsonl log file and extracts token telemetry events."""
        target = file_path if file_path else self.log_file
        try:
            with open(target, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    data = record.get("data") or {}
                    agent_id = record.get("agent_id") or "unknown"
                    
                    p_tokens = data.get("prompt_tokens") or data.get("tokens_in")
                    c_tokens = data.get("completion_tokens") or data.get("tokens_out")
                    if p_tokens or c_tokens:
                        p_val = int(p_tokens or 0)
                        c_val = int(c_tokens or 0)
                        self._record_agent_usage(
                            agent_id,
                            {"prompt_tokens": p_val, "completion_tokens": c_val},
                            agent_usages,
                            tier_usage,
                        )
        except Exception:
            pass
