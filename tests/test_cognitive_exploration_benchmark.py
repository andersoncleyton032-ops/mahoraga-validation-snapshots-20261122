from experiments.cognitive_exploration_benchmark import run_cognitive_exploration_benchmark


def test_benchmark_is_deterministic_and_advisory_only():
    first = run_cognitive_exploration_benchmark()
    second = run_cognitive_exploration_benchmark()
    assert first["benchmark_sha256"] == second["benchmark_sha256"]
    assert first["synthetic_only"] is True
    assert first["hardware_telemetry_used"] is False
    assert first["memory_persisted"] is False
    assert first["goal_created"] is False
    assert first["work_executed"] is False
    assert first["authorization_granted"] is False


def test_healthy_homeostasis_retains_highest_value_within_reduced_budget():
    result = run_cognitive_exploration_benchmark()
    healthy = result["scenarios"][0]
    baseline = healthy["baseline_without_homeostasis"]
    adaptive = healthy["homeostasis_adaptive"]
    assert baseline["selected_count"] == 3
    assert adaptive["selected_count"] == 2
    assert adaptive["selected_ids"][0] == "high-value"
    assert adaptive["aggregate_cost"]["runtime_ms"] <= 10_000
    assert adaptive["aggregate_cost"]["ram_mb"] <= 1024


def test_load_ablation_changes_only_the_modeled_load_channel():
    result = run_cognitive_exploration_benchmark()
    scenario = result["scenarios"][1]
    ablation = scenario["load_ablation"]
    assert ablation["full_load_factor"] == scenario["effective_exploration_factor"]
    assert ablation["full_load_factor"] < ablation["no_load_factor"]
    assert ablation["full_load"]["selected_count"] == 0
    assert ablation["no_load"]["selected_count"] == 2
    assert scenario["baseline_without_homeostasis"]["selected_count"] == 3


def test_critical_pressure_defers_adaptive_selection_but_baseline_has_no_gate():
    result = run_cognitive_exploration_benchmark()
    scenario = result["scenarios"][2]
    assert scenario["control_state"] == "pause"
    assert scenario["adaptive_status"] == "deferred"
    assert scenario["homeostasis_adaptive"]["selected_count"] == 0
    assert scenario["baseline_without_homeostasis"]["selected_count"] == 3
    assert scenario["execution_performed"] is False
    assert scenario["authorization_granted"] is False
