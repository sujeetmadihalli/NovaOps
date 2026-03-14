"""Evaluation harness — runs scenarios against the war room and scores results.

Usage:
    python -m evaluation.runner --list              # Show all scenarios
    python -m evaluation.runner --scenario 1        # Run one scenario
    python -m evaluation.runner --all               # Run all scenarios
    python -m evaluation.runner --domain oom        # Run all OOM scenarios
"""

import sys
import json
import time
import logging
import argparse
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from agents.main import _extract_action_from_text
from agents.schemas import parse_war_room
from agents.artifacts import _extract_message_text
from evaluation.scenarios import SCENARIOS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("novaops.eval")

RESULTS_DIR = Path(__file__).parent.parent / "evaluation" / "results"


def inject_mock_data(scenario: dict):
    """Patch the singleton aggregators with scenario-specific mock data."""
    import tools.investigation as inv

    mock = scenario["mock_data"]

    inv._logs._get_mock_logs = lambda svc: mock["logs"]
    inv._metrics._get_mock_metrics = lambda svc: mock["metrics"]
    inv._k8s._get_mock_events = lambda svc: mock["k8s_events"]
    inv._github._get_mock_commits = lambda *a, **kw: mock["github"]


def run_scenario(scenario: dict) -> dict:
    """Run a single scenario through the war room. Returns result dict."""
    from agents.graph import build_war_room

    print(f"\n{'='*60}")
    print(f"  Scenario {scenario['id']}: {scenario['name']}")
    print(f"  Domain: {scenario['domain']} | Difficulty: {scenario['difficulty']}")
    print(f"  Expected: {scenario['expected_tool']}")
    print(f"{'='*60}")

    # Inject mock data
    inject_mock_data(scenario)

    start_time = time.time()
    try:
        graph, domain = build_war_room(scenario["alert_text"])
        graph_result = graph(scenario["alert_text"])
        elapsed = time.time() - start_time

        # Extract node texts for schema parsing
        node_texts = {}
        if hasattr(graph_result, "results") and isinstance(graph_result.results, dict):
            for node_name, node_result in graph_result.results.items():
                if node_result and hasattr(node_result, "result"):
                    node_texts[node_name] = _extract_message_text(node_result.result)

        # Parse into typed schemas
        war_room = parse_war_room(node_texts)

        # Score: use schema-based action extraction
        expected = scenario["expected_tool"]
        proposed_action = war_room.proposed_action()

        # Fallback to raw text parsing if schema didn't extract
        if proposed_action.get("tool") == "noop_require_human":
            result_text = str(graph_result)
            proposed_action = _extract_action_from_text(result_text)
        else:
            result_text = war_room.summary_text() or str(graph_result)

        tool_found = proposed_action.get("tool") == expected
        domain_correct = domain == scenario["domain"]

        # Schema quality metrics
        schema_quality = {
            "triage_valid": war_room.triage is not None and war_room.triage.is_valid(),
            "analysts_valid": sum(1 for a in war_room.analysts.values() if a.is_valid()),
            "analysts_total": len(war_room.analysts),
            "root_cause_valid": war_room.root_cause is not None and war_room.root_cause.is_valid(),
            "critic_valid": war_room.critic is not None and war_room.critic.is_valid(),
            "remediation_valid": war_room.remediation is not None and war_room.remediation.is_valid(),
        }
        schema_score = sum([
            schema_quality["triage_valid"],
            schema_quality["analysts_valid"] >= 3,
            schema_quality["root_cause_valid"],
            schema_quality["critic_valid"],
            schema_quality["remediation_valid"],
        ]) / 5.0

        print(f"\n  Domain: {'PASS' if domain_correct else 'FAIL'} ({domain})")
        print(f"  Tool: {'PASS' if tool_found else 'FAIL'} (looking for '{expected}')")
        print(f"  Schema: {schema_score:.0%} ({schema_quality})")
        print(f"  Time: {elapsed:.1f}s")

        return {
            "scenario_id": scenario["id"],
            "scenario_name": scenario["name"],
            "domain_expected": scenario["domain"],
            "domain_actual": domain,
            "domain_correct": domain_correct,
            "expected_tool": expected,
            "parsed_tool": proposed_action.get("tool"),
            "tool_found": tool_found,
            "schema_quality": schema_quality,
            "schema_score": round(schema_score, 2),
            "elapsed_seconds": round(elapsed, 1),
            "result_text": result_text[:2000],
            "status": "completed",
        }
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"\n  ERROR: {e}")
        return {
            "scenario_id": scenario["id"],
            "scenario_name": scenario["name"],
            "status": "error",
            "error": str(e),
            "elapsed_seconds": round(elapsed, 1),
        }


def save_results(results: List[dict]):
    """Save evaluation results to JSON."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_path = RESULTS_DIR / f"eval-{timestamp}.json"

    completed = [r for r in results if r["status"] == "completed"]
    summary = {
        "timestamp": datetime.now().isoformat(),
        "total_scenarios": len(results),
        "completed": len(completed),
        "domain_accuracy": sum(1 for r in results if r.get("domain_correct")) / max(len(results), 1),
        "tool_accuracy": sum(1 for r in results if r.get("tool_found")) / max(len(results), 1),
        "schema_accuracy": sum(r.get("schema_score", 0) for r in completed) / max(len(completed), 1),
        "avg_time_seconds": sum(r.get("elapsed_seconds", 0) for r in results) / max(len(results), 1),
        "results": results,
    }

    output_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\n{'='*60}")
    print(f"  Evaluation Summary")
    print(f"{'='*60}")
    print(f"  Scenarios: {summary['total_scenarios']}")
    print(f"  Completed: {summary['completed']}")
    print(f"  Domain Accuracy: {summary['domain_accuracy']:.0%}")
    print(f"  Tool Accuracy: {summary['tool_accuracy']:.0%}")
    print(f"  Schema Quality: {summary['schema_accuracy']:.0%}")
    print(f"  Avg Time: {summary['avg_time_seconds']:.1f}s")
    print(f"  Results saved: {output_path}")

    return summary


def main():
    parser = argparse.ArgumentParser(description="NovaOps v2 Evaluation Harness")
    parser.add_argument("--list", action="store_true", help="List all scenarios")
    parser.add_argument("--scenario", type=int, help="Run a specific scenario by ID")
    parser.add_argument("--all", action="store_true", help="Run all scenarios")
    parser.add_argument("--domain", type=str, help="Run all scenarios for a domain")
    args = parser.parse_args()

    if args.list:
        print(f"\n{'ID':>3} | {'Domain':<20} | {'Difficulty':<8} | {'Expected Tool':<22} | Name")
        print("-" * 90)
        for s in SCENARIOS:
            print(f"{s['id']:>3} | {s['domain']:<20} | {s['difficulty']:<8} | {s['expected_tool']:<22} | {s['name']}")
        return

    scenarios_to_run = []

    if args.scenario:
        scenarios_to_run = [s for s in SCENARIOS if s["id"] == args.scenario]
        if not scenarios_to_run:
            print(f"Scenario {args.scenario} not found.")
            return
    elif args.domain:
        scenarios_to_run = [s for s in SCENARIOS if s["domain"] == args.domain]
        if not scenarios_to_run:
            print(f"No scenarios for domain '{args.domain}'.")
            return
    elif args.all:
        scenarios_to_run = SCENARIOS
    else:
        parser.print_help()
        return

    results = []
    for scenario in scenarios_to_run:
        result = run_scenario(scenario)
        results.append(result)

    save_results(results)


if __name__ == "__main__":
    main()
