"""
Evaluation Framework — Self-Aware Hybrid Threat Analyzer
Runs all scenarios, computes metrics, and generates a report.

Usage:
  1. Start the server:  python -m uvicorn app.main:app --reload
  2. Run evaluation:    python evaluation/evaluate_bot.py
"""

import sys
import os
import json
import time
import requests
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from evaluation.scenario_runner import build_all_scenarios

API_BASE = "http://localhost:8000"


def reset_all_sessions():
    """Reset all server session state."""
    try:
        requests.post(f"{API_BASE}/reset_session", timeout=5)
    except Exception:
        pass


def run_scenario(scenario):
    """Execute a single scenario and return the result."""
    endpoint = scenario["endpoint"]
    url = API_BASE + endpoint

    try:
        start = time.time()
        r = requests.post(url, json=scenario["payload"], timeout=30)
        latency = round((time.time() - start) * 1000, 1)

        result = {
            "name": scenario["name"],
            "model": scenario["model"],
            "category": scenario["category"],
            "expected": scenario["expected"],
            "group": scenario.get("group", ""),
            "status_code": r.status_code,
            "latency_ms": latency,
        }

        if r.status_code == 200:
            data = r.json()
            net = data.get("network", {})
            fusion = data.get("fusion", {})
            action = data.get("action", {})
            threat = data.get("threat_context")

            result["network_risk"] = net.get("network_risk", 0.0)
            result["network_decision"] = net.get("decision", "?")
            result["attack_type"] = net.get("attack_type")
            result["confidence"] = net.get("confidence", 0.0)
            result["behavioral_risk"] = data.get("behavioral", {}).get("behavioral_risk", 0.0)
            result["fused_risk"] = fusion.get("final_risk", 0.0)
            result["fused_decision"] = fusion.get("decision", "?")
            result["action"] = action.get("action", "?")
            result["threat_detected"] = threat is not None
            result["threat_type"] = threat.get("attack_type") if threat else None
            result["passed"] = True

        elif r.status_code == 403:
            result["action"] = "ACCOUNT_LOCKED"
            result["fused_risk"] = 1.0
            result["network_risk"] = 0.0
            result["behavioral_risk"] = 0.0
            result["fused_decision"] = "BLOCK"
            result["passed"] = True
            result["threat_detected"] = False
            result["attack_type"] = None

        else:
            result["error"] = r.text[:200]
            result["passed"] = False
            result["threat_detected"] = False

        return result

    except Exception as e:
        return {
            "name": scenario["name"],
            "model": scenario["model"],
            "category": scenario["category"],
            "expected": scenario["expected"],
            "group": scenario.get("group", ""),
            "passed": False,
            "error": str(e),
            "threat_detected": False,
        }


def compute_metrics(results):
    """Compute evaluation metrics from results."""

    metrics = {
        "total_scenarios": len(results),
        "successful_runs": sum(1 for r in results if r.get("passed")),
        "failed_runs": sum(1 for r in results if not r.get("passed")),
    }

    # Per-model stats
    by_model = defaultdict(lambda: {
        "total": 0, "benign": 0, "attack": 0,
        "benign_correct": 0, "attack_detected": 0,
        "risks": [], "latencies": [],
    })

    for r in results:
        if not r.get("passed"):
            continue
        # Skip escalation and raw_http from per-model stats
        if r.get("group") in ("escalation", "raw_http"):
            continue

        model = r["model"]
        m = by_model[model]
        m["total"] += 1
        m["latencies"].append(r.get("latency_ms", 0))

        if r["category"] == "benign":
            m["benign"] += 1
            risk = r.get("fused_risk", 0.0)
            if r.get("fused_decision") == "ALLOW":
                m["benign_correct"] += 1
            m["risks"].append(("benign", risk))
        else:
            m["attack"] += 1
            risk = r.get("fused_risk", 0.0)
            detected = (
                risk > 0.3 or
                r.get("threat_detected", False) or
                r.get("network_decision") == "ANOMALY" or
                r.get("action") in ("ACCOUNT_LOCKED", "REQUIRE_MFA")
            )
            if detected:
                m["attack_detected"] += 1
            m["risks"].append(("attack", risk))

    model_metrics = {}
    for model, m in by_model.items():
        benign_accuracy = m["benign_correct"] / m["benign"] if m["benign"] > 0 else 0
        attack_detection = m["attack_detected"] / m["attack"] if m["attack"] > 0 else 0
        avg_latency = sum(m["latencies"]) / len(m["latencies"]) if m["latencies"] else 0

        model_metrics[model] = {
            "total_scenarios": m["total"],
            "benign_count": m["benign"],
            "attack_count": m["attack"],
            "benign_accuracy": round(benign_accuracy, 4),
            "attack_detection_rate": round(attack_detection, 4),
            "avg_latency_ms": round(avg_latency, 1),
        }

    metrics["by_model"] = model_metrics

    # Session escalation analysis
    escalation_results = [r for r in results if r.get("group") == "escalation"]
    if escalation_results:
        actions = [r.get("action", "?") for r in escalation_results]
        metrics["escalation_sequence"] = actions
        metrics["escalation_blocked"] = "ACCOUNT_LOCKED" in actions

    # HTTP signature detection
    raw_results = [r for r in results if r.get("group") == "raw_http"]
    if raw_results:
        raw_attacks = [r for r in raw_results if r["category"] == "attack"]
        threats_found = sum(
            1 for r in raw_attacks
            if r.get("threat_detected", False) or
               r.get("action") == "ACCOUNT_LOCKED" or
               r.get("fused_decision") in ("MFA", "BLOCK")
        )
        metrics["http_signature_detection"] = {
            "total_attack_scenarios": len(raw_attacks),
            "threats_detected": threats_found,
            "detection_rate": round(threats_found / len(raw_attacks), 4) if raw_attacks else 0,
        }

    return metrics


def print_report(results, metrics):
    """Print formatted evaluation report."""

    print()
    print("=" * 80)
    print(" SELF-AWARE HYBRID THREAT ANALYZER - EVALUATION REPORT ".center(80))
    print(f" Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ".center(80))
    print("=" * 80)

    print(f"\n  Total Scenarios: {metrics['total_scenarios']}")
    print(f"  Successful:      {metrics['successful_runs']}")
    print(f"  Failed:          {metrics['failed_runs']}")

    # Per-model table
    print("\n" + "-" * 80)
    print(" PER-MODEL EVALUATION ".center(80))
    print("-" * 80)
    print(f"  {'Model':<14} {'Total':>6} {'Benign':>8} {'Attack':>8} {'Ben.Acc':>9} {'Det.Rate':>10} {'Latency':>10}")
    print("  " + "-" * 68)

    for model, m in metrics.get("by_model", {}).items():
        print(f"  {model:<14} {m['total_scenarios']:>6} {m['benign_count']:>8} {m['attack_count']:>8}"
              f" {m['benign_accuracy']:>8.1%} {m['attack_detection_rate']:>9.1%} {m['avg_latency_ms']:>8.1f}ms")

    # Detailed results
    print("\n" + "-" * 80)
    print(" DETAILED SCENARIO RESULTS ".center(80))
    print("-" * 80)

    current_group = None
    for r in results:
        group = r.get("group", "")
        if group != current_group:
            current_group = group
            print(f"\n  --- {group.upper()} ---")

        name = r["name"][:42]
        cat = "BEN" if r["category"] == "benign" else "ATK"

        if not r.get("passed"):
            status = "FAIL"
            detail = r.get("error", "")[:30]
        elif r.get("action") == "ACCOUNT_LOCKED":
            status = "BLOCK"
            detail = f"fused={r.get('fused_risk', 0):.3f}"
        elif r.get("threat_detected"):
            status = "THREAT"
            detail = r.get("threat_type", "?")[:20]
        else:
            risk = r.get("fused_risk", 0)
            atk = r.get("attack_type")
            status = r.get("fused_decision", "?")[:5]
            detail = f"fused={risk:.3f}" + (f" [{atk}]" if atk else "")

        print(f"  [{cat}] {name:42s} {status:6s} {detail}")

    # Session escalation
    if "escalation_sequence" in metrics:
        print("\n" + "-" * 80)
        print(" SESSION ESCALATION TEST ".center(80))
        print("-" * 80)
        for i, action in enumerate(metrics["escalation_sequence"]):
            icon = "X" if action == "ACCOUNT_LOCKED" else "!" if action == "REQUIRE_MFA" else "."
            print(f"  [{icon}] Request #{i+1}: {action}")
        verdict = "PASS" if metrics["escalation_blocked"] else "FAIL"
        print(f"\n  Escalation to BLOCK: {verdict}")

    # HTTP signature detection
    if "http_signature_detection" in metrics:
        hsd = metrics["http_signature_detection"]
        print("\n" + "-" * 80)
        print(" HTTP SIGNATURE DETECTION ".center(80))
        print("-" * 80)
        print(f"  Attack scenarios tested: {hsd['total_attack_scenarios']}")
        print(f"  Threats detected:        {hsd['threats_detected']}")
        print(f"  Detection rate:          {hsd['detection_rate']:.1%}")

    print("\n" + "=" * 80)


def save_report(results, metrics, path="evaluation/report.json"):
    """Save results and metrics as JSON."""
    report = {
        "timestamp": datetime.now().isoformat(),
        "metrics": {k: v for k, v in metrics.items() if k != "by_model"},
        "model_metrics": metrics.get("by_model", {}),
        "results": results,
    }

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"  Report saved to: {path}")


def main():
    """Run full evaluation."""

    print("\n  Resetting all sessions...")
    reset_all_sessions()

    print("  Building scenarios...")
    scenarios = build_all_scenarios()
    print(f"  Total scenarios: {len(scenarios)}")

    print("\n  Running evaluation...\n")
    results = []
    current_group = None

    for i, scenario in enumerate(scenarios):
        # Reset session when group changes (except escalation - needs accumulation)
        group = scenario.get("group", "")
        if group != current_group and group != "escalation":
            user_id = scenario["payload"].get("user_id")
            if user_id:
                requests.post(f"{API_BASE}/reset_session?user_id={user_id}", timeout=5)
        current_group = group

        result = run_scenario(scenario)
        results.append(result)

        icon = "+" if result.get("passed") else "X"
        risk = result.get("fused_risk", 0)
        print(f"  [{i+1:2d}/{len(scenarios)}] {icon} {scenario['name'][:48]:48s} risk={risk:.3f}")

    # Compute and display
    metrics = compute_metrics(results)
    print_report(results, metrics)
    save_report(results, metrics)


if __name__ == "__main__":
    main()
