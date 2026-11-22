import pytest

from agent.autonomy_governor import AutonomyGovernor, AutonomyGovernorError
from agent.dharma import Dharma


class FakeHardware:
    def battery(self):
        return {}

    def memory(self):
        return {}

    def storage(self):
        return {}

    def thermal(self):
        return {}


def make_governor(tmp_path):
    return AutonomyGovernor(FakeHardware(), Dharma(tmp_path))


def resource_snapshot(
    *,
    charging="CHARGING",
    percentage=80,
    ram_mb=4096,
    free_storage_mb=4096,
):
    return {
        "battery": {
            "termux_api": {
                "data": {"percentage": percentage, "status": charging}
            },
            "sysfs_read_only": {},
        },
        "memory": {
            "status": "ok",
            "values": {"MemAvailable": {"mb": ram_mb}},
        },
        "storage": {
            "project": {"free_bytes": free_storage_mb * 1024 * 1024},
        },
        "thermal": {},
    }


def interactive_context(**updates):
    data = {
        "app_foreground": True,
        "screen_interactive": True,
        "thermal_status": "normal",
    }
    data.update(updates)
    return data


def test_charging_foreground_session_gets_bounded_budget(tmp_path):
    governor = make_governor(tmp_path)

    session = governor.evaluate_session(
        interactive_context(),
        resource_snapshot=resource_snapshot(),
    )

    assert session["status"] == "bounded"
    assert session["mode"] == "foreground_charging"
    assert session["budget"]["max_task_seconds"] == 20
    assert session["budget"]["max_task_ram_mb"] == 256
    assert session["budget"]["max_concurrent_tasks"] == 1
    assert session["budget"]["continuous_loop_allowed"] is False
    assert session["budget"]["network_allowed"] is False


def test_unknown_thermal_state_reduces_charging_budget(tmp_path):
    governor = make_governor(tmp_path)

    session = governor.evaluate_session(
        interactive_context(thermal_status="unknown"),
        resource_snapshot=resource_snapshot(),
    )

    assert session["status"] == "bounded"
    assert session["budget"]["max_task_seconds"] == 5
    assert session["budget"]["max_task_ram_mb"] == 64
    assert "thermal_unknown_reduced_budget" in session["reasons"]


def test_background_or_noninteractive_context_never_gets_compute_budget(tmp_path):
    governor = make_governor(tmp_path)

    for context in (
        interactive_context(app_foreground=False),
        interactive_context(screen_interactive=False),
    ):
        session = governor.evaluate_session(
            context,
            resource_snapshot=resource_snapshot(),
        )
        assert session["status"] == "paused"
        assert session["mode"] == "deferred_background"
        assert session["budget"]["max_task_seconds"] == 0


def test_severe_thermal_or_low_resources_pause_autonomous_work(tmp_path):
    governor = make_governor(tmp_path)

    hot = governor.evaluate_session(
        interactive_context(thermal_status="severe"),
        resource_snapshot=resource_snapshot(),
    )
    low_memory = governor.evaluate_session(
        interactive_context(),
        resource_snapshot=resource_snapshot(ram_mb=512),
    )
    low_storage = governor.evaluate_session(
        interactive_context(),
        resource_snapshot=resource_snapshot(free_storage_mb=256),
    )

    assert hot["status"] == "paused"
    assert low_memory["status"] == "paused"
    assert low_storage["status"] == "paused"


def test_missing_foreground_state_pauses_instead_of_guessing(tmp_path):
    governor = make_governor(tmp_path)

    session = governor.evaluate_session(
        {"screen_interactive": True},
        resource_snapshot=resource_snapshot(),
    )

    assert session["status"] == "paused"
    assert session["mode"] == "runtime_context_unknown"
    assert session["runtime_context"]["app_foreground"] is None
    assert "app_foreground_unknown" in session["reasons"]


def test_local_task_permit_is_bounded_and_has_no_side_effects(tmp_path):
    governor = make_governor(tmp_path)
    session = governor.evaluate_session(
        interactive_context(),
        resource_snapshot=resource_snapshot(),
    )
    request = {
        "task_id": "analyze-memory-patterns",
        "risk": "local_compute",
        "estimated_seconds": 10,
        "estimated_ram_mb": 128,
    }

    result = governor.evaluate_work(session, request)

    assert result["allowed"] is True
    assert result["permit"]["max_runtime_seconds"] == 10
    assert result["permit"]["max_memory_mb"] == 128
    assert result["permit"]["continuous_loop"] is False
    assert result["permit"]["execution_performed"] is False


def test_work_requiring_network_sensor_capture_or_project_writes_is_blocked(tmp_path):
    governor = make_governor(tmp_path)
    session = governor.evaluate_session(
        interactive_context(),
        resource_snapshot=resource_snapshot(),
    )

    for field in ("requires_network", "requires_camera", "requires_microphone", "writes_project"):
        result = governor.evaluate_work(session, {
            "risk": "local_compute",
            "estimated_seconds": 1,
            "estimated_ram_mb": 16,
            field: True,
        })
        assert result["allowed"] is False
        assert result["reason"] == "work_exceeds_initial_autonomy_scope"


def test_task_over_budget_and_unknown_risk_are_rejected(tmp_path):
    governor = make_governor(tmp_path)
    session = governor.evaluate_session(
        interactive_context(),
        resource_snapshot=resource_snapshot(),
    )

    too_large = governor.evaluate_work(session, {
        "risk": "local_compute",
        "estimated_seconds": 21,
        "estimated_ram_mb": 128,
    })
    unknown = governor.evaluate_work(session, {
        "risk": "root_device",
        "estimated_seconds": 1,
        "estimated_ram_mb": 16,
    })
    assert too_large["reason"] == "task_exceeds_time_budget"
    assert unknown["reason"] == "risk_not_allowlisted"
    with pytest.raises(AutonomyGovernorError, match="booleano"):
        malformed = governor.evaluate_work(session, {
            "risk": "local_compute",
            "estimated_seconds": 1,
            "estimated_ram_mb": 16,
            "requires_network": "yes",
        })


def test_learning_progress_beats_unstructured_novelty_and_is_not_self_certified(tmp_path):
    governor = make_governor(tmp_path)
    result = governor.rank_initiatives([
        {
            "candidate_id": "learning-progress",
            "title": "Melhorar predição",
            "kind": "experience_pattern",
            "priority": "normal",
            "evidence": {
                "learning_progress": 0.9,
                "uncertainty_reducible": 0.9,
                "episode_count": 5,
                "validated_episode_count": 5,
            },
        },
        {
            "candidate_id": "novelty-only",
            "title": "Fonte imprevisível",
            "kind": "capability_gap",
            "priority": "critical",
            "evidence": {"novelty": 1.0},
        },
    ])

    assert result["ranking"][0]["candidate_id"] == "learning-progress"
    assert result["automatic_adoption"] is False
    assert result["ranking"][0]["epistemic_note"].startswith("Independência das fontes não confirmada")


def test_measured_prediction_regression_reduces_initiative_score(tmp_path):
    governor = make_governor(tmp_path)
    result = governor.rank_initiatives([
        {
            "candidate_id": "improving",
            "priority": "normal",
            "evidence": {
                "learning_progress": 0.6,
                "uncertainty_reducible": 0.7,
                "episode_count": 5,
                "validated_episode_count": 5,
                "prediction_regression": 0.0,
            },
        },
        {
            "candidate_id": "regressing",
            "priority": "normal",
            "evidence": {
                "learning_progress": 0.6,
                "uncertainty_reducible": 0.7,
                "episode_count": 5,
                "validated_episode_count": 5,
                "prediction_regression": 1.0,
            },
        },
    ])

    improving, regressing = result["ranking"]
    assert improving["candidate_id"] == "improving"
    assert improving["score"] > regressing["score"]
    assert regressing["components"]["prediction_regression"] == 1.0
    assert result["automatic_adoption"] is False



def test_numeric_parser_rejects_unrepresentably_large_integer(tmp_path):
    governor = make_governor(tmp_path)
    assert governor._number(10 ** 10000) is None


def test_candidate_cannot_self_certify_source_independence(tmp_path):
    governor = make_governor(tmp_path)
    base = {
        "priority": "normal",
        "evidence": {
            "learning_progress": 0.6,
            "uncertainty_reducible": 0.4,
            "episode_count": 5,
            "validated_episode_count": 5,
        },
    }
    unclaimed = dict(base, candidate_id="unclaimed")
    claimed = {
        **base,
        "candidate_id": "claimed",
        "evidence": {
            **base["evidence"],
            "source_independence_verified": True,
        },
    }

    result = governor.rank_initiatives([unclaimed, claimed])
    ranking = {item["candidate_id"]: item for item in result["ranking"]}

    assert ranking["claimed"]["score"] == ranking["unclaimed"]["score"]
    assert ranking["claimed"]["components"]["source_independence_verified"] is False
    assert ranking["claimed"]["components"]["source_independence_claimed"] is True
    assert ranking["claimed"]["epistemic_note"].startswith(
        "Independência das fontes não confirmada"
    )


def test_work_session_rejects_caller_modified_budget(tmp_path):
    governor = make_governor(tmp_path)
    session = governor.evaluate_session(
        interactive_context(),
        resource_snapshot=resource_snapshot(),
    )
    forged = dict(session)
    forged["budget"] = dict(session["budget"])
    forged["budget"]["max_task_seconds"] = 3600
    forged["budget"]["max_task_ram_mb"] = 1_000_000

    result = governor.evaluate_work(forged, {
        "risk": "local_compute",
        "estimated_seconds": 100,
        "estimated_ram_mb": 100_000,
    })

    assert result["allowed"] is False
    assert result["reason"] == "session_invalid_expired_or_already_consumed"


def test_work_session_is_single_use_and_bound_to_issuing_governor(tmp_path):
    governor = make_governor(tmp_path)
    session = governor.evaluate_session(
        interactive_context(),
        resource_snapshot=resource_snapshot(),
    )
    request = {
        "risk": "local_compute",
        "estimated_seconds": 1,
        "estimated_ram_mb": 16,
    }

    first = governor.evaluate_work(session, request)
    replay = governor.evaluate_work(session, request)
    other_governor = make_governor(tmp_path / "other")
    cross_instance = other_governor.evaluate_work(session, request)

    assert first["allowed"] is True
    assert first["permit"]["execution_performed"] is False
    assert replay["allowed"] is False
    assert cross_instance["allowed"] is False


def test_expired_work_session_is_rejected(tmp_path):
    governor = make_governor(tmp_path)
    session = governor.evaluate_session(
        interactive_context(),
        resource_snapshot=resource_snapshot(),
    )
    governor._active_sessions[session["session_id"]] = 0.0

    result = governor.evaluate_work(session, {
        "risk": "local_compute",
        "estimated_seconds": 1,
        "estimated_ram_mb": 16,
    })

    assert result["allowed"] is False
    assert result["reason"] == "session_invalid_expired_or_already_consumed"


def test_missing_android_runtime_context_pauses_instead_of_guessing(tmp_path):
    governor = make_governor(tmp_path)

    session = governor.evaluate_session(
        None,
        resource_snapshot=resource_snapshot(),
    )

    assert session["status"] == "paused"
    assert session["mode"] == "runtime_context_unknown"
    assert session["runtime_context"]["app_foreground"] is None
    assert session["runtime_context"]["screen_interactive"] is None
    assert "app_foreground_unknown" in session["reasons"]
    assert "screen_interactive_unknown" in session["reasons"]


def test_runtime_context_with_unknown_foreground_or_display_pauses(tmp_path):
    governor = make_governor(tmp_path)

    session = governor.evaluate_session(
        {
            "app_foreground": True,
            "screen_interactive": None,
            "thermal_status": "normal",
        },
        resource_snapshot=resource_snapshot(),
    )

    assert session["status"] == "paused"
    assert session["mode"] == "runtime_context_unknown"
    assert session["budget"]["max_task_seconds"] == 0


def test_runtime_context_false_foreground_defers_even_if_screen_is_on(tmp_path):
    governor = make_governor(tmp_path)

    session = governor.evaluate_session(
        {
            "app_foreground": False,
            "screen_interactive": True,
            "thermal_status": "normal",
        },
        resource_snapshot=resource_snapshot(),
    )

    assert session["status"] == "paused"
    assert session["mode"] == "deferred_background"
    assert "app_not_foreground" in session["reasons"]


def test_governor_uses_live_hardware_runtime_context_when_none_supplied(tmp_path):
    class ContextHardware(FakeHardware):
        def runtime_context(self):
            return {
                "app_foreground": True,
                "screen_interactive": True,
                "thermal_status": "normal",
                "source": "test_fixture",
                "status": "available",
            }

    governor = AutonomyGovernor(ContextHardware(), Dharma(tmp_path))
    session = governor.evaluate_session(
        None,
        resource_snapshot=resource_snapshot(),
    )

    assert session["status"] == "bounded"
    assert session["mode"] == "foreground_charging"
    assert session["runtime_context"]["source"] == "test_fixture"



def background_context(**updates):
    data = {
        "app_foreground": False,
        "screen_interactive": False,
        "charging": True,
        "thermal_status": "normal",
        "source": "test_fixture",
        "status": "available",
    }
    data.update(updates)
    return data


def test_screen_off_background_idle_gets_one_checkpointable_task_budget(tmp_path):
    governor = make_governor(tmp_path)
    session = governor.evaluate_session(
        background_context(),
        resource_snapshot=resource_snapshot(),
        work_mode="background_idle",
    )

    assert session["status"] == "bounded"
    assert session["mode"] == "background_idle"
    assert session["budget"]["max_task_seconds"] == 20
    assert session["budget"]["max_task_ram_mb"] == 128
    assert session["budget"]["max_concurrent_tasks"] == 1
    assert session["budget"]["continuous_loop_allowed"] is False
    assert session["budget"]["workspace_writes_allowed"] is False

    result = governor.evaluate_work(session, {
        "task_id": "nightly-internal-analysis",
        "risk": "local_compute",
        "estimated_seconds": 10,
        "estimated_ram_mb": 96,
        "internal_only": True,
        "checkpointable": True,
    })
    assert result["allowed"] is True
    assert result["permit"]["execution_mode"] == "background_idle"
    assert result["permit"]["checkpoint_required"] is True
    assert result["permit"]["continuous_loop"] is False


@pytest.mark.parametrize(
    "context,resources,reason",
    [
        (background_context(app_foreground=True), resource_snapshot(), "background_requires_mahoraga_app_not_foreground"),
        (background_context(screen_interactive=True), resource_snapshot(), "background_requires_screen_off"),
        (background_context(charging=False), resource_snapshot(charging="DISCHARGING", percentage=10), "background_battery_below_critical_minimum"),
        (background_context(thermal_status="severe"), resource_snapshot(), "background_thermal_state_critical"),
        (background_context(), resource_snapshot(ram_mb=256), "available_memory_below_emergency_floor"),
        (background_context(), resource_snapshot(free_storage_mb=256), "free_storage_below_emergency_floor"),
    ],
)
def test_background_idle_fails_closed_when_any_required_condition_is_missing(
    tmp_path, context, resources, reason
):
    governor = make_governor(tmp_path)
    session = governor.evaluate_session(
        context, resource_snapshot=resources, work_mode="background_idle"
    )
    assert session["status"] == "paused"
    assert session["mode"] == "background_idle_pause"
    assert session["budget"]["max_task_seconds"] == 0
    assert reason in session["reasons"]


def test_background_idle_requires_internal_and_checkpointable_work(tmp_path):
    governor = make_governor(tmp_path)
    session = governor.evaluate_session(
        background_context(),
        resource_snapshot=resource_snapshot(),
        work_mode="background_idle",
    )
    missing_checkpoint = governor.evaluate_work(session, {
        "risk": "local_compute",
        "estimated_seconds": 1,
        "estimated_ram_mb": 16,
        "internal_only": True,
    })
    assert missing_checkpoint["allowed"] is False
    assert missing_checkpoint["reason"] == "background_task_must_be_checkpointable"


def test_background_idle_does_not_allow_workspace_or_project_writes(tmp_path):
    governor = make_governor(tmp_path)
    session = governor.evaluate_session(
        background_context(),
        resource_snapshot=resource_snapshot(),
        work_mode="background_idle",
    )
    result = governor.evaluate_work(session, {
        "risk": "local_compute",
        "estimated_seconds": 1,
        "estimated_ram_mb": 16,
        "internal_only": True,
        "checkpointable": True,
        "writes_workspace": True,
    })
    assert result["allowed"] is False
    assert result["reason"] == "work_exceeds_initial_autonomy_scope"



def test_background_companion_allows_chat_in_foreground_with_smaller_budget(tmp_path):
    governor = make_governor(tmp_path)
    session = governor.evaluate_session(
        background_context(screen_interactive=True),
        resource_snapshot=resource_snapshot(),
        work_mode="background_companion",
    )

    assert session["status"] == "bounded"
    assert session["mode"] == "background_companion"
    assert session["budget"]["max_task_seconds"] == 8
    assert session["budget"]["max_task_ram_mb"] == 64
    assert session["budget"]["max_concurrent_tasks"] == 1
    assert session["budget"]["continuous_loop_allowed"] is False

    permit = governor.evaluate_work(session, {
        "task_id": "companion-chat-internal-work",
        "risk": "local_compute",
        "estimated_seconds": 6,
        "estimated_ram_mb": 48,
        "internal_only": True,
        "checkpointable": True,
    })
    assert permit["allowed"] is True
    assert permit["permit"]["execution_mode"] == "background_companion"
    assert permit["permit"]["checkpoint_required"] is True


def test_background_companion_reduces_budget_for_light_thermal_state(tmp_path):
    governor = make_governor(tmp_path)
    session = governor.evaluate_session(
        background_context(screen_interactive=True, thermal_status="light"),
        resource_snapshot=resource_snapshot(),
        work_mode="background_companion",
    )

    assert session["status"] == "bounded"
    assert session["budget"]["max_task_seconds"] == 5
    assert session["budget"]["max_task_ram_mb"] == 48


@pytest.mark.parametrize(
    "context,resources,reason",
    [
        (background_context(app_foreground=True, screen_interactive=True), resource_snapshot(), "background_requires_mahoraga_app_not_foreground"),
        (background_context(screen_interactive=False), resource_snapshot(), "companion_mode_requires_interactive_screen"),
        (background_context(charging=False, screen_interactive=True), resource_snapshot(charging="DISCHARGING", percentage=10), "background_battery_below_critical_minimum"),
        (background_context(screen_interactive=True, thermal_status="severe"), resource_snapshot(), "background_thermal_state_critical"),
        (background_context(screen_interactive=True), resource_snapshot(ram_mb=256), "available_memory_below_emergency_floor"),
        (background_context(screen_interactive=True), resource_snapshot(free_storage_mb=256), "free_storage_below_emergency_floor"),
    ],
)
def test_background_companion_fails_closed_when_a_required_condition_is_missing(
    tmp_path, context, resources, reason
):
    governor = make_governor(tmp_path)
    session = governor.evaluate_session(
        context, resource_snapshot=resources, work_mode="background_companion"
    )
    assert session["status"] == "paused"
    assert session["mode"] == "background_companion_pause"
    assert session["budget"]["max_task_seconds"] == 0
    assert reason in session["reasons"]





def test_background_companion_can_run_on_battery_without_charging(tmp_path):
    governor = make_governor(tmp_path)
    session = governor.evaluate_session(
        background_context(charging=False, screen_interactive=True),
        resource_snapshot(charging="DISCHARGING", percentage=75),
        work_mode="background_companion",
    )
    assert session["status"] == "bounded"
    assert session["budget"]["max_task_seconds"] == 8
    assert session["budget"]["max_task_ram_mb"] == 64
    assert "running_on_battery_with_adaptive_budget" in session["reasons"]


@pytest.mark.parametrize("ram_mb,storage_mb", [(1536, 4096), (4096, 1536), (1536, 1536)])
def test_two_gib_headroom_is_preferred_not_a_hard_background_gate(
    tmp_path, ram_mb, storage_mb
):
    governor = make_governor(tmp_path)
    session = governor.evaluate_session(
        background_context(screen_interactive=True, charging=False),
        resource_snapshot(
            charging="DISCHARGING", percentage=75,
            ram_mb=ram_mb, free_storage_mb=storage_mb,
        ),
        work_mode="background_companion",
    )
    assert session["status"] == "bounded"
    assert session["budget"]["max_task_seconds"] == 8
    assert session["budget"]["max_task_ram_mb"] == 64
    if ram_mb < 2048:
        assert "memory_below_preferred_headroom" in session["reasons"]
    if storage_mb < 2048:
        assert "storage_below_preferred_headroom" in session["reasons"]


def test_unknown_thermal_state_keeps_only_a_minimal_companion_budget(tmp_path):
    governor = make_governor(tmp_path)
    session = governor.evaluate_session(
        background_context(screen_interactive=True, thermal_status="unknown"),
        resource_snapshot(),
        work_mode="background_companion",
    )
    assert session["status"] == "bounded"
    assert session["budget"]["max_task_seconds"] == 2
    assert session["budget"]["max_task_ram_mb"] == 16


def test_background_companion_requires_internal_and_checkpointable_work(tmp_path):
    governor = make_governor(tmp_path)
    session = governor.evaluate_session(
        background_context(screen_interactive=True),
        resource_snapshot=resource_snapshot(),
        work_mode="background_companion",
    )
    missing_checkpoint = governor.evaluate_work(session, {
        "risk": "local_compute",
        "estimated_seconds": 1,
        "estimated_ram_mb": 16,
        "internal_only": True,
    })

    assert missing_checkpoint["allowed"] is False
    assert missing_checkpoint["reason"] == "background_task_must_be_checkpointable"
