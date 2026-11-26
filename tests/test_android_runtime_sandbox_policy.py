from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRIDGE = (
    ROOT
    / "android-runtime"
    / "app"
    / "src"
    / "main"
    / "java"
    / "com"
    / "mahoraga"
    / "runtime"
    / "TermuxBridge.java"
)


def test_bridge_does_not_probe_termux_private_internal_storage():
    source = BRIDGE.read_text(encoding="utf-8")

    assert "java.io.File" not in source
    assert "timeoutExecutable.isFile()" not in source
    assert "timeoutExecutable.canExecute()" not in source
    assert "new File(termuxInfo.dataDir" not in source
    assert "termuxInfo.dataDir + \"/files/usr/bin\"" in source


def test_result_pending_intent_identity_contains_unique_request_id():
    source = BRIDGE.read_text(encoding="utf-8")

    assert ".setData(Uri.parse(resultIntentDataUri(requestId)))" in source
    assert 'return "mahoraga://termux-result/" + requestId;' in source


def test_result_waiter_is_cleaned_even_when_pending_intent_creation_fails():
    source = BRIDGE.read_text(encoding="utf-8")

    assert "PendingIntent resultPendingIntent = null;" in source
    assert "finally {" in source
    assert "if (resultPendingIntent != null) resultPendingIntent.cancel();" in source
    assert "TermuxResultReceiver.cancel(requestId, future);" in source

def test_android_main_sources_do_not_call_post_min_sdk_string_isblank():
    java_root = ROOT / "android-runtime" / "app" / "src" / "main" / "java"
    sources = list(java_root.rglob("*.java"))

    assert sources
    assert all(".isBlank()" not in source.read_text(encoding="utf-8") for source in sources)

def test_termux_command_description_does_not_claim_network_isolation():
    source = BRIDGE.read_text(encoding="utf-8")

    assert "No network access." not in source
    assert "This worker does not request network tools." in source

