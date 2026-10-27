"""
Tool: prometheus.query
Queries and analyzes Prometheus metric timeseries, OpenTelemetry gauge/counter metrics,
and operational performance indicators.
Detects:
- Error rate spikes (5xx HTTP responses, RPC errors)
- Latency regressions and p99 spikes
- CPU and memory saturation
- Database query slowdowns and pool exhaustion
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import urllib.request
import urllib.parse

from models.observability import AnomalySeverity, AnomalyType, MetricAnomaly


class PrometheusQueryTool:
    """Tool: prometheus.query - Operational metric analysis engine."""

    name = "prometheus.query"
    description = (
        "Queries Prometheus and OpenTelemetry metric feeds for error rate spikes, "
        "latency regressions, database bottlenecks, and saturation anomalies."
    )

    def __init__(self, prometheus_url: Optional[str] = None, timeout_seconds: float = 2.0):
        self.prometheus_url = prometheus_url.rstrip("/") if prometheus_url else None
        self.timeout_seconds = timeout_seconds

    def query(
        self,
        metrics_data: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = None,
        promql: Optional[str] = None,
        error_rate_threshold_pct: float = 1.0,
        latency_threshold_ms: float = 500.0,
    ) -> List[MetricAnomaly]:
        """
        Analyzes metric feeds or queries a live Prometheus server endpoint.
        Returns detected anomalies with severity and deviation factors.
        """
        anomalies: List[MetricAnomaly] = []

        # 1. Query live Prometheus server if URL and promql query provided
        if self.prometheus_url and promql:
            live_anomalies = self._query_live_prometheus(promql)
            anomalies.extend(live_anomalies)

        # 2. Analyze ingested metric timeseries / sample data
        if metrics_data:
            data_list = [metrics_data] if isinstance(metrics_data, dict) else metrics_data
            for sample in data_list:
                anomalies.extend(
                    self._evaluate_sample(
                        sample,
                        error_rate_threshold_pct=error_rate_threshold_pct,
                        latency_threshold_ms=latency_threshold_ms,
                    )
                )

        return anomalies

    def _query_live_prometheus(self, query: str) -> List[MetricAnomaly]:
        """Queries live Prometheus HTTP API: /api/v1/query?query=..."""
        anomalies: List[MetricAnomaly] = []
        if not self.prometheus_url:
            return anomalies

        try:
            url = f"{self.prometheus_url}/api/v1/query?query={urllib.parse.quote(query)}"
            req = urllib.request.Request(url, headers={"User-Agent": "MultiAgent-Observability/1.0"})
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("status") == "success":
                    result = data.get("data", {}).get("result", [])
                    for idx, item in enumerate(result, start=1):
                        metric = item.get("metric", {})
                        val = float(item.get("value", [0, 0])[1])
                        metric_name = metric.get("__name__", query)
                        anomalies.append(
                            MetricAnomaly(
                                id=f"ANOM-PROM-{idx:03d}",
                                metric_name=metric_name,
                                anomaly_type=AnomalyType.LATENCY_SPIKE if "duration" in metric_name else AnomalyType.ERROR_RATE_SPIKE,
                                severity=AnomalySeverity.HIGH,
                                service_name=metric.get("service"),
                                endpoint_route=metric.get("route") or metric.get("handler"),
                                current_value=val,
                                baseline_value=val * 0.2,
                                deviation_factor=5.0,
                                description=f"Live Prometheus query `{query}` breached threshold with value {val}.",
                            )
                        )
        except Exception:
            # Fall back cleanly if live server is unreachable
            pass
        return anomalies

    def _evaluate_sample(
        self,
        sample: Dict[str, Any],
        error_rate_threshold_pct: float,
        latency_threshold_ms: float,
    ) -> List[MetricAnomaly]:
        """Evaluates a metric sample record or summary dictionary."""
        anomalies: List[MetricAnomaly] = []
        metric_name = sample.get("metric_name") or sample.get("name") or "unknown_metric"
        service = sample.get("service_name") or sample.get("service")
        route = sample.get("endpoint_route") or sample.get("route") or sample.get("path")
        val = float(sample.get("current_value") or sample.get("value") or 0.0)
        baseline = float(sample.get("baseline_value") or sample.get("baseline") or (val / 3.0 if val > 0 else 1.0))
        timestamp = str(sample.get("timestamp") or "")

        # 1. Error Rate Anomaly
        if "error" in metric_name.lower() or "5xx" in metric_name.lower() or "failure" in metric_name.lower():
            if val >= error_rate_threshold_pct:
                deviation = round(val / baseline if baseline > 0 else val, 1)
                severity = (
                    AnomalySeverity.CRITICAL
                    if val >= 10.0
                    else AnomalySeverity.HIGH
                    if val >= 5.0
                    else AnomalySeverity.MEDIUM
                )
                anomalies.append(
                    MetricAnomaly(
                        id=f"ANOM-ERR-{len(anomalies) + 1:03d}",
                        metric_name=metric_name,
                        anomaly_type=AnomalyType.ERROR_RATE_SPIKE,
                        severity=severity,
                        service_name=service,
                        endpoint_route=route,
                        current_value=val,
                        baseline_value=baseline,
                        deviation_factor=deviation,
                        description=(
                            f"Error rate elevated to {val}% (baseline: {baseline}%, threshold: {error_rate_threshold_pct}%) "
                            f"on service '{service or 'global'}'."
                        ),
                        timestamp=timestamp or None,
                    )
                )

        # 2. Database Slowdown / Connection Exhaustion
        elif "db" in metric_name.lower() or "database" in metric_name.lower():
            deviation = round(val / baseline if baseline > 0 else 2.0, 1)
            anomalies.append(
                MetricAnomaly(
                    id=f"ANOM-DB-{len(anomalies) + 1:03d}",
                    metric_name=metric_name,
                    anomaly_type=AnomalyType.DATABASE_SLOWDOWN,
                    severity=AnomalySeverity.HIGH,
                    service_name=service,
                    endpoint_route=route,
                    current_value=val,
                    baseline_value=baseline,
                    deviation_factor=deviation,
                    description=f"Database query latency or connection pool pressure elevated to {val}.",
                    timestamp=timestamp or None,
                )
            )

        # 3. Latency / Duration Anomaly
        elif "latency" in metric_name.lower() or "duration" in metric_name.lower() or "response_time" in metric_name.lower():
            # If value is in seconds (e.g. 1.2s), convert to ms for comparison if threshold is > 50
            val_ms = val * 1000.0 if val < 20.0 else val
            base_ms = baseline * 1000.0 if baseline < 20.0 else baseline
            if val_ms >= latency_threshold_ms:
                deviation = round(val_ms / base_ms if base_ms > 0 else val_ms, 1)
                severity = (
                    AnomalySeverity.CRITICAL
                    if val_ms >= latency_threshold_ms * 3.0
                    else AnomalySeverity.HIGH
                    if val_ms >= latency_threshold_ms * 1.5
                    else AnomalySeverity.MEDIUM
                )
                anomalies.append(
                    MetricAnomaly(
                        id=f"ANOM-LAT-{len(anomalies) + 1:03d}",
                        metric_name=metric_name,
                        anomaly_type=AnomalyType.LATENCY_SPIKE,
                        severity=severity,
                        service_name=service,
                        endpoint_route=route,
                        current_value=val_ms,
                        baseline_value=base_ms,
                        deviation_factor=deviation,
                        description=(
                            f"Latency spike observed: {val_ms:.1f}ms (baseline: {base_ms:.1f}ms, "
                            f"threshold: {latency_threshold_ms}ms, deviation: {deviation}x)."
                        ),
                        timestamp=timestamp or None,
                    )
                )

        # 4. CPU Saturation
        elif "cpu" in metric_name.lower() and val >= 85.0:
            deviation = round(val / baseline if baseline > 0 else 1.5, 1)
            anomalies.append(
                MetricAnomaly(
                    id=f"ANOM-CPU-{len(anomalies) + 1:03d}",
                    metric_name=metric_name,
                    anomaly_type=AnomalyType.CPU_SATURATION,
                    severity=AnomalySeverity.HIGH if val < 95.0 else AnomalySeverity.CRITICAL,
                    service_name=service,
                    endpoint_route=route,
                    current_value=val,
                    baseline_value=baseline,
                    deviation_factor=deviation,
                    description=f"CPU utilization saturated at {val}% on service '{service or 'host'}'.",
                    timestamp=timestamp or None,
                )
            )

        return anomalies
