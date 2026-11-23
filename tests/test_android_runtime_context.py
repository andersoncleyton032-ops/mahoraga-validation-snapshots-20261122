import pytest

from agent.hardware_intelligence import HardwareIntelligence


def test_runtime_context_parses_termux_foreground_active_display_and_thermal_status():
    result = HardwareIntelligence.parse_runtime_context(
        power_output=(
            "mWakefulness=Awake\n"
            "mInteractive=true\n"
            "Display Power: state=ON, brightness=0.75\n"
        ),
        activities_output=(
            "mResumedActivity: ActivityRecord{abc u0 com.termux/.app.TermuxActivity t42}\n"
        ),
        thermal_output="Thermal Status: 2\n",
    )
    assert result["app_foreground"] is True
    assert result["foreground_package"] == "com.termux"
    assert result["screen_interactive"] is True
    assert result["power_manager_interactive"] is True
    assert result["display_state"] == "ON"
    assert result["thermal_status"] == "moderate"
    assert result["thermal_status_code"] == 2
    assert result["read_only"] is True


def test_runtime_context_rejects_other_foreground_apps_for_termux_work():
    result = HardwareIntelligence.parse_runtime_context(
        power_output="mInteractive=true\nDisplay Power: state=ON\n",
        activities_output=(
            "topResumedActivity=ActivityRecord{abc u0 "
            "com.android.settings/.Settings t4}\n"
        ),
        thermal_output="Thermal Status: 0\n",
    )
    assert result["app_foreground"] is False
    assert result["foreground_package"] == "com.android.settings"
    assert result["screen_interactive"] is True
    assert result["thermal_status"] == "normal"


def test_runtime_context_keeps_unknown_display_foreground_and_thermal_unknown():
    result = HardwareIntelligence.parse_runtime_context(
        power_output="mInteractive=true\n",
        activities_output="no resumed activity record was exposed\n",
        thermal_output="Current temperatures from HAL: none\n",
    )
    assert result["app_foreground"] is None
    assert result["screen_interactive"] is None
    assert result["thermal_status"] == "unknown"
    assert result["thermal_status_code"] is None


def test_runtime_context_maps_severe_thermal_status_to_blocking_state():
    result = HardwareIntelligence.parse_runtime_context(
        power_output="mInteractive=true\nDisplay Power: state=ON\n",
        activities_output=(
            "topResumedActivity=ActivityRecord{abc u0 "
            "com.termux/.app.TermuxActivity t1}\n"
        ),
        thermal_output="Thermal Status: 3\n",
    )
    assert result["thermal_status"] == "severe"


def test_runtime_context_rejects_non_text_dumpsys_inputs():
    with pytest.raises(ValueError, match="textos"):
        HardwareIntelligence.parse_runtime_context("", None, "")


def test_runtime_context_reports_unavailable_without_rish(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "agent.hardware_intelligence.shutil.which",
        lambda _name: None,
    )
    monkeypatch.setenv("HOME", str(tmp_path))
    result = HardwareIntelligence(root=tmp_path).runtime_context()
    assert result["available"] is False
    assert result["status"] == "rish_not_found"
    assert result["app_foreground"] is None
    assert result["screen_interactive"] is None
    assert result["thermal_status"] == "unknown"


def test_runtime_context_prefers_top_resumed_over_legacy_resumed_field():
    result = HardwareIntelligence.parse_runtime_context(
        power_output="mInteractive=true\nDisplay Power: state=ON\n",
        activities_output=(
            "mResumedActivity: ActivityRecord{abc u0 com.termux/.app.TermuxActivity t42}\n"
            "topResumedActivity=ActivityRecord{def u0 com.android.settings/.Settings t43}\n"
        ),
        thermal_output="Thermal Status: 0\n",
    )
    assert result["foreground_package"] == "com.android.settings"
    assert result["app_foreground"] is False


def test_runtime_context_caps_dumpsys_output_before_parsing(monkeypatch, tmp_path):
    from types import SimpleNamespace

    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        captured["script"] = argv[-1]
        return SimpleNamespace(
            stdout="x" * (160 * 1024 + 1),
            stderr="",
            returncode=0,
        )

    monkeypatch.setattr("agent.hardware_intelligence.shutil.which", lambda _name: "/mock/rish")
    monkeypatch.setattr("agent.hardware_intelligence.subprocess.run", fake_run)
    monkeypatch.setenv("HOME", str(tmp_path))

    result = HardwareIntelligence(root=tmp_path).runtime_context()

    assert captured["argv"][:2] == ["/mock/rish", "-c"]
    assert "dumpsys power | head -c 65536" in captured["script"]
    assert "dumpsys activity activities | head -c 65536" in captured["script"]
    assert "dumpsys thermalservice | head -c 16384" in captured["script"]
    assert captured["kwargs"]["timeout"] == 10
    assert result["available"] is False
    assert result["status"] == "runtime_output_too_large"
    assert result["app_foreground"] is None
    assert result["screen_interactive"] is None
