#!/usr/bin/env python3
"""Chaos scenario runner for RCA-Operator Phase 2 validation.

Drives deterministic failure patterns against the rca-demo microservices,
then asserts that the operator emits the expected IncidentReport CRs.

Usage:
    python runner.py --scenario payment_outage
    python runner.py --all
    python runner.py --list

Exit codes:
    0  all (non-optional) expectations satisfied
    1  one or more expectations failed
    2  configuration / runtime error
"""
from __future__ import annotations

import argparse
import json
import logging
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
import yaml
from kubernetes import client, config

LOG = logging.getLogger("chaos-runner")
GROUP = "rca.rca-operator.tech"
VERSION = "v1alpha1"
PLURAL = "incidentreports"


@dataclass
class Expectation:
    incident_type: str
    workload: str
    min_count: int = 1
    optional: bool = False

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Expectation":
        return cls(
            incident_type=d["incident_type"],
            workload=d["workload"],
            min_count=int(d.get("min_count", 1)),
            optional=bool(d.get("optional", False)),
        )


@dataclass
class Scenario:
    name: str
    description: str
    targets: Dict[str, Dict[str, float]]
    expectations: List[Expectation]
    duration_seconds: int
    workload: List[Dict[str, Any]]
    concurrency: int
    rps: int
    frontend_url: str
    namespace: str
    assert_timeout_seconds: int
    poll_interval_seconds: int


def load_scenarios(path: Path) -> Dict[str, Scenario]:
    raw = yaml.safe_load(path.read_text())
    defaults = raw.get("defaults", {})
    out: Dict[str, Scenario] = {}
    for name, body in raw.get("scenarios", {}).items():
        out[name] = Scenario(
            name=name,
            description=body.get("description", ""),
            targets=body.get("targets", {}),
            expectations=[Expectation.from_dict(e) for e in body.get("expect", {}).get("incidents", [])],
            duration_seconds=int(body.get("duration_seconds", defaults.get("duration_seconds", 90))),
            workload=body.get("workload", defaults.get("workload", [])),
            concurrency=int(body.get("concurrency", defaults.get("concurrency", 8))),
            rps=int(body.get("rps", defaults.get("rps", 10))),
            frontend_url=body.get("frontend_url", defaults.get("frontend_url")),
            namespace=body.get("namespace", defaults.get("namespace", "rca-demo")),
            assert_timeout_seconds=int(body.get("assert_timeout_seconds", defaults.get("assert_timeout_seconds", 180))),
            poll_interval_seconds=int(body.get("poll_interval_seconds", defaults.get("poll_interval_seconds", 5))),
        )
    return out


def apply_chaos(service: str, namespace: str, overrides: Dict[str, float]) -> None:
    url = f"http://{service}.{namespace}.svc.cluster.local:8080/chaos/config"
    resp = requests.post(url, json={"overrides": overrides}, timeout=10)
    resp.raise_for_status()
    LOG.info("chaos applied to %s: %s", service, overrides)


def reset_chaos(service: str, namespace: str) -> None:
    url = f"http://{service}.{namespace}.svc.cluster.local:8080/chaos/reset"
    try:
        requests.post(url, timeout=10).raise_for_status()
        LOG.info("chaos reset on %s", service)
    except Exception as exc:
        LOG.warning("failed to reset chaos on %s: %s", service, exc)


class WorkloadDriver:
    """Drives the frontend with a weighted request mix at a target RPS."""

    def __init__(self, frontend_url: str, workload: List[Dict[str, Any]], concurrency: int, rps: int) -> None:
        self.frontend_url = frontend_url.rstrip("/")
        self.workload = workload
        self.concurrency = concurrency
        self.rps = max(1, rps)
        self.stop_event = threading.Event()
        self.sent = 0
        self.errors = 0
        self._lock = threading.Lock()

    def _pick(self) -> Dict[str, Any]:
        weights = [int(r.get("weight", 1)) for r in self.workload]
        return random.choices(self.workload, weights=weights, k=1)[0]

    def _one(self) -> None:
        req = self._pick()
        url = f"{self.frontend_url}{req['path']}"
        try:
            requests.request(
                method=req["method"],
                url=url,
                json=req.get("body"),
                timeout=10,
            )
            with self._lock:
                self.sent += 1
        except Exception:
            with self._lock:
                self.errors += 1

    def run(self, duration_seconds: int) -> None:
        end = time.time() + duration_seconds
        interval = 1.0 / self.rps
        with ThreadPoolExecutor(max_workers=self.concurrency) as ex:
            while time.time() < end and not self.stop_event.is_set():
                ex.submit(self._one)
                time.sleep(interval)
        LOG.info("workload complete: sent=%d errors=%d", self.sent, self.errors)


def k8s_client() -> client.CustomObjectsApi:
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()
    return client.CustomObjectsApi()


def list_incidents(api: client.CustomObjectsApi, namespace: str) -> List[Dict[str, Any]]:
    resp = api.list_namespaced_custom_object(group=GROUP, version=VERSION, namespace=namespace, plural=PLURAL)
    return resp.get("items", [])


def incident_matches(item: Dict[str, Any], exp: Expectation) -> bool:
    spec = item.get("spec", {})
    itype = spec.get("incidentType", "")
    if itype != exp.incident_type:
        return False
    scope = spec.get("scope", {})
    for ref_key in ("workloadRef", "resourceRef"):
        ref = scope.get(ref_key) or {}
        if ref.get("name") == exp.workload:
            return True
    labels = item.get("metadata", {}).get("labels", {}) or {}
    if labels.get("rca.rca-operator.tech/workload") == exp.workload:
        return True
    return False


def snapshot_existing(api: client.CustomObjectsApi, namespace: str) -> set:
    return {item["metadata"]["uid"] for item in list_incidents(api, namespace)}


def wait_for_expectations(
    api: client.CustomObjectsApi,
    scenario: Scenario,
    baseline_uids: set,
    scenario_started: float,
) -> List[tuple]:
    """Poll until all non-optional expectations are met or timeout.

    Returns a list of (expectation, matched_count, incidents) tuples.
    """
    deadline = time.time() + scenario.assert_timeout_seconds
    results: Dict[int, tuple] = {}

    while time.time() < deadline:
        items = list_incidents(api, scenario.namespace)
        for idx, exp in enumerate(scenario.expectations):
            matched: List[Dict[str, Any]] = []
            for it in items:
                # Only count incidents that are new OR have activity after scenario start.
                uid = it["metadata"]["uid"]
                status = it.get("status", {}) or {}
                active_at = status.get("activeAt") or status.get("firstObservedAt") or ""
                is_new = uid not in baseline_uids
                is_reactivated = bool(active_at) and active_at >= time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(scenario_started)
                )
                if (is_new or is_reactivated) and incident_matches(it, exp):
                    matched.append(it)
            results[idx] = (exp, len(matched), matched)

        # Stop polling early if all non-optional expectations are met.
        unmet = [r for r in results.values() if not r[0].optional and r[1] < r[0].min_count]
        if not unmet:
            break
        time.sleep(scenario.poll_interval_seconds)

    return list(results.values())


def run_scenario(scenario: Scenario) -> bool:
    LOG.info("=== scenario: %s ===", scenario.name)
    LOG.info("%s", scenario.description)

    api = k8s_client()
    baseline_uids = snapshot_existing(api, scenario.namespace)
    scenario_started = time.time()

    # Apply chaos to all target services.
    for service, overrides in scenario.targets.items():
        apply_chaos(service, scenario.namespace, overrides)

    try:
        driver = WorkloadDriver(scenario.frontend_url, scenario.workload, scenario.concurrency, scenario.rps)
        driver.run(scenario.duration_seconds)

        LOG.info("awaiting IncidentReport expectations (timeout=%ds)...", scenario.assert_timeout_seconds)
        results = wait_for_expectations(api, scenario, baseline_uids, scenario_started)
    finally:
        for service in scenario.targets.keys():
            reset_chaos(service, scenario.namespace)

    all_passed = True
    LOG.info("--- results: %s ---", scenario.name)
    for exp, count, _ in results:
        tag = "OPT" if exp.optional else "REQ"
        ok = count >= exp.min_count
        status = "PASS" if ok else "FAIL"
        LOG.info(
            "[%s][%s] incidentType=%s workload=%s matched=%d (min=%d)",
            tag,
            status,
            exp.incident_type,
            exp.workload,
            count,
            exp.min_count,
        )
        if not ok and not exp.optional:
            all_passed = False

    return all_passed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenarios-file", default=str(Path(__file__).parent / "scenarios.yaml"))
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--scenario", help="Run a single named scenario")
    group.add_argument("--all", action="store_true", help="Run every scenario sequentially")
    group.add_argument("--list", action="store_true", help="List available scenarios")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    scenarios = load_scenarios(Path(args.scenarios_file))

    if args.list:
        for name, sc in scenarios.items():
            print(f"{name}: {sc.description}")
        return 0

    to_run: List[Scenario] = []
    if args.all:
        to_run = list(scenarios.values())
    else:
        if args.scenario not in scenarios:
            LOG.error("unknown scenario %s. Known: %s", args.scenario, ", ".join(scenarios))
            return 2
        to_run = [scenarios[args.scenario]]

    failed = []
    for sc in to_run:
        try:
            if not run_scenario(sc):
                failed.append(sc.name)
        except Exception as exc:
            LOG.exception("scenario %s raised: %s", sc.name, exc)
            failed.append(sc.name)

    if failed:
        LOG.error("FAILED scenarios: %s", ", ".join(failed))
        return 1
    LOG.info("ALL scenarios passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
