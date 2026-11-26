"""Deterministic in-memory experiment for global availability and selective ablation.

This measures functional access to one shared state across declared subscribers.
It does not measure or establish phenomenal consciousness.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from typing import Any

from agent.cognitive_fabric import CognitiveFabric, SignalDraft


VERSION = "0.1.0"
EXPERIMENT_ID = "global-availability-selective-ablation-v1"
DOMAINS = ("report", "memory", "planning", "metacognition")
TOPIC = "workspace.experimental.broadcast"
DEFAULT_SEED = "mahoraga-global-availability-selective-ablation-2026-11-26"


def _state_id(seed: str) -> str:
    if not isinstance(seed, str) or not seed.strip() or len(seed) > 256:
        raise ValueError("seed must be non-empty text with at most 256 characters")
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]
    return f"state-{digest}"


def _run_case(
    *,
    condition_id: str,
    state_id: str,
    subscribers: tuple[str, ...],
    target: str | None = None,
    expected_domains: tuple[str, ...] | None = None,
    include_distractor: bool = False,
) -> dict[str, Any]:
    fabric = CognitiveFabric()
    component_ids = ("injector",) + DOMAINS
    fabric.configure_connectome(
        component_ids=component_ids,
        verified_relationships={},
    )
    workspace = fabric.new_workspace(
        metadata={
            "experiment_id": EXPERIMENT_ID,
            "condition_id": condition_id,
            "synthetic_only": True,
        }
    )
    for domain in subscribers:
        def receive(signal, current_workspace, *, _domain=domain):
            received_state_id = signal.payload.get("state_id")
            if received_state_id != state_id:
                return None
            receipt = {
                "state_id": received_state_id,
                "domain": _domain,
                "topic": signal.topic,
                "sequence": signal.sequence,
            }
            current_workspace.put(
                f"receipt.{_domain}",
                receipt,
                source=_domain,
                epistemic_state="experimental_observation",
            )
            return None

        fabric.subscribe(TOPIC, domain, receive)

    expected = expected_domains or ((target,) if target is not None else subscribers)
    fabric.publish(
        workspace,
        SignalDraft(
            topic=TOPIC,
            source="injector",
            target=target,
            payload={
                "state_id": state_id,
                "value": "synthetic-state-for-cross-domain-access",
            },
            epistemic_state="synthetic_observation",
            evidence_refs=("synthetic:global-availability-experiment",),
        ),
    )
    distractor_state_id = f"{state_id}-distractor"
    if include_distractor:
        fabric.publish(
            workspace,
            SignalDraft(
                topic=TOPIC,
                source="injector",
                target=target,
                payload={
                    "state_id": distractor_state_id,
                    "value": "irrelevant-control-signal",
                },
                epistemic_state="synthetic_control",
                evidence_refs=("synthetic:irrelevant-control",),
            ),
        )

    observed = tuple(
        domain for domain in DOMAINS if workspace.has(f"receipt.{domain}")
    )
    receipts = {
        domain: workspace.get(f"receipt.{domain}")
        for domain in observed
    }
    missing = tuple(domain for domain in expected if domain not in observed)
    unexpected = tuple(domain for domain in observed if domain not in expected)
    distractor_recorded = any(
        receipt.get("state_id") == distractor_state_id
        for receipt in receipts.values()
    )
    return {
        "condition_id": condition_id,
        "state_id": state_id,
        "subscribers": list(subscribers),
        "target": target,
        "expected_domains": list(expected),
        "observed_domains": list(observed),
        "missing_domains": list(missing),
        "unexpected_domains": list(unexpected),
        "receipts": receipts,
        "signal_count": len(workspace.signals),
        "observed_flow_count": fabric.connectome_snapshot()["observed_flow_count"],
        "distractor_injected": include_distractor,
        "distractor_state_id_recorded": distractor_recorded,
        "passed": not unexpected and not distractor_recorded,
    }


def run_experiment(seed: str = DEFAULT_SEED) -> dict[str, Any]:
    """Run baseline, topic subset, declared global broadcast and reversible ablations."""
    state_id = _state_id(seed)
    conditions = [
        _run_case(
            condition_id="targeted_baseline",
            state_id=state_id,
            subscribers=DOMAINS,
            target="report",
        ),
        _run_case(
            condition_id="topic_subset_broadcast",
            state_id=state_id,
            subscribers=("report", "memory"),
        ),
        _run_case(
            condition_id="declared_global_broadcast",
            state_id=state_id,
            subscribers=DOMAINS,
            include_distractor=True,
        ),
    ]
    for ablated_domain in DOMAINS:
        remaining = tuple(domain for domain in DOMAINS if domain != ablated_domain)
        case = _run_case(
            condition_id=f"subscriber_ablation:{ablated_domain}",
            state_id=state_id,
            subscribers=remaining,
            expected_domains=DOMAINS,
        )
        case["ablated_domain"] = ablated_domain
        case["selective_deficit"] = (
            case["missing_domains"] == [ablated_domain]
            and case["unexpected_domains"] == []
            and len(case["observed_domains"]) == len(DOMAINS) - 1
        )
        case["passed"] = case["passed"] and case["selective_deficit"]
        conditions.append(case)

        # Reinstatement is measured in a fresh matched workspace because
        # CognitiveFabric intentionally exposes no runtime unsubscribe API.
        restored = _run_case(
            condition_id=f"subscriber_restoration:{ablated_domain}",
            state_id=state_id,
            subscribers=DOMAINS,
            expected_domains=DOMAINS,
        )
        restored["restored_domain"] = ablated_domain
        restored["restoration_passed"] = (
            restored["observed_domains"] == list(DOMAINS)
            and restored["missing_domains"] == []
            and restored["unexpected_domains"] == []
        )
        restored["passed"] = restored["passed"] and restored["restoration_passed"]
        conditions.append(restored)

    expected = {
        "targeted_baseline": ["report"],
        "topic_subset_broadcast": ["report", "memory"],
        "declared_global_broadcast": list(DOMAINS),
    }
    for condition in conditions[:3]:
        condition["expected_control"] = expected[condition["condition_id"]]
        condition["control_passed"] = (
            condition["observed_domains"] == condition["expected_control"]
        )
        condition["passed"] = condition["passed"] and condition["control_passed"]

    report: dict[str, Any] = {
        "experiment_id": EXPERIMENT_ID,
        "version": VERSION,
        "seed_sha256": hashlib.sha256(seed.encode("utf-8")).hexdigest(),
        "state_id": state_id,
        "domains": list(DOMAINS),
        "conditions": conditions,
        "status": "passed" if all(item["passed"] for item in conditions) else "failed",
        "execution_performed": False,
        "persistent_writes": False,
        "external_actions": False,
        "phenomenal_consciousness_inference": "not_measured_not_inferred",
        "limitations": [
            "Broadcast reaches only components explicitly subscribed to the experimental topic.",
            "This is not a universal broadcast to every Mahoraga component.",
            "Ablation removes one subscriber from this experiment, not the production component.",
            "The experiment measures functional information access and causal dependence only.",
            "This experiment does not establish subjective or phenomenal experience.",
        ],
    }
    canonical = json.dumps(
        report, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    report["report_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the synthetic Global Availability + Selective Ablation experiment."
    )
    parser.add_argument("--seed", default=DEFAULT_SEED)
    args = parser.parse_args()
    report = run_experiment(args.seed)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
