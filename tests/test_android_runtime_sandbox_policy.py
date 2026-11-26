import json
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



def test_termux_signer_is_verified_before_any_run_command_dispatch():
    source = BRIDGE.read_text(encoding="utf-8")
    activity = (
        ROOT
        / "android-runtime"
        / "app"
        / "src"
        / "main"
        / "java"
        / "com"
        / "mahoraga"
        / "runtime"
        / "MainActivity.java"
    ).read_text(encoding="utf-8")

    assert "TermuxSignerPolicy.verify(termuxPackage, Build.VERSION.SDK_INT)" in source
    assert 'ExecutionResult.failure("termux_signer_untrusted", false)' in source
    assert "termux_signer_inspection_failed" in source
    assert source.index("TermuxSignerPolicy.verify(termuxPackage") < source.index(
        "startTermuxCommand(app, command)"
    )
    assert "TermuxBridge.verifyInstalledSigner(this)" in activity
    assert activity.index("TermuxBridge.verifyInstalledSigner(this)") < activity.index(
        "WorkScheduler.start(this)"
    )


def test_wake_receiver_fails_closed_when_sender_uid_is_not_verifiable():
    receiver = (
        ROOT
        / "android-runtime"
        / "app"
        / "src"
        / "main"
        / "java"
        / "com"
        / "mahoraga"
        / "runtime"
        / "WakeRequestReceiver.java"
    ).read_text(encoding="utf-8")
    policy = (
        ROOT
        / "android-runtime"
        / "app"
        / "src"
        / "main"
        / "java"
        / "com"
        / "mahoraga"
        / "runtime"
        / "WorkPolicy.java"
    ).read_text(encoding="utf-8")

    assert "? getSentFromUid()" in receiver
    assert ": -1;" in receiver
    assert "WorkPolicy.isTrustedWakeSender(" in receiver
    assert "catch (RuntimeException senderInspectionFailure)" in receiver
    assert "return supportsAuthenticatedWake(sdkInt)" in policy
    assert "termuxUid >= 0" in policy
    assert "senderUid == termuxUid" in policy


def test_interrupted_termux_result_wait_restores_thread_interrupt_flag():
    source = BRIDGE.read_text(encoding="utf-8")

    assert "catch (InterruptedException interrupted)" in source
    assert "Thread.currentThread().interrupt();" in source
    assert '"termux_result_wait_interrupted"' in source


def test_existing_schedule_is_stopped_if_termux_signer_becomes_untrusted():
    activity = (
        ROOT
        / "android-runtime"
        / "app"
        / "src"
        / "main"
        / "java"
        / "com"
        / "mahoraga"
        / "runtime"
        / "MainActivity.java"
    ).read_text(encoding="utf-8")
    startup = activity.split("if (WorkScheduler.isEnabled(this))", 1)[1].split(
        "refreshWorkStatus();", 1
    )[0]

    assert "TermuxBridge.verifyInstalledSigner(this)" in startup
    assert "if (!signer.trusted)" in startup
    assert "WorkScheduler.stop(this);" in startup


def test_background_execution_is_disabled_below_authenticated_wake_api_floor():
    policy = (
        ROOT
        / "android-runtime"
        / "app"
        / "src"
        / "main"
        / "java"
        / "com"
        / "mahoraga"
        / "runtime"
        / "WorkPolicy.java"
    ).read_text(encoding="utf-8")
    activity = (
        ROOT
        / "android-runtime"
        / "app"
        / "src"
        / "main"
        / "java"
        / "com"
        / "mahoraga"
        / "runtime"
        / "MainActivity.java"
    ).read_text(encoding="utf-8")
    worker = (
        ROOT
        / "android-runtime"
        / "app"
        / "src"
        / "main"
        / "java"
        / "com"
        / "mahoraga"
        / "runtime"
        / "MahoragaOneShotWorker.java"
    ).read_text(encoding="utf-8")
    bridge = BRIDGE.read_text(encoding="utf-8")

    assert "return sdkInt >= 34;" in policy
    assert "WorkPolicy.supportsAuthenticatedWake(Build.VERSION.SDK_INT)" in activity
    assert "WorkScheduler.stop(this);" in activity
    assert "WorkPolicy.supportsAuthenticatedWake(Build.VERSION.SDK_INT)" in worker
    assert '"authenticated_wake_requires_api34"' in worker
    assert "WorkPolicy.supportsAuthenticatedWake(Build.VERSION.SDK_INT)" in bridge


def test_model_provider_authenticates_termux_uid_and_release_signer():
    provider = (
        ROOT
        / "android-runtime"
        / "app"
        / "src"
        / "main"
        / "java"
        / "com"
        / "mahoraga"
        / "runtime"
        / "ModelRuntimeProvider.kt"
    ).read_text(encoding="utf-8")
    policy = (
        ROOT
        / "android-runtime"
        / "app"
        / "src"
        / "main"
        / "java"
        / "com"
        / "mahoraga"
        / "runtime"
        / "TermuxCallerPolicy.kt"
    ).read_text(encoding="utf-8")

    assert "Binder.getCallingUid()" in provider
    assert "getPackagesForUid(callingUid)" in provider
    assert "getApplicationInfo(" in provider
    assert "TermuxSignerPolicy.verifyInstalled(" in provider
    assert "TermuxCallerPolicy.isTrusted(" in provider
    assert "callingUid == installedTermuxUid" in policy
    assert "packagesForUid?.contains(TERMUX_PACKAGE) == true" in policy
    assert "&& signerTrusted" in policy


def test_native_model_load_requires_cpu_policy_and_expected_sha256():
    provider = (
        ROOT
        / "android-runtime"
        / "app"
        / "src"
        / "main"
        / "java"
        / "com"
        / "mahoraga"
        / "runtime"
        / "ModelRuntimeProvider.kt"
    ).read_text(encoding="utf-8")
    owner = (
        ROOT
        / "android-runtime"
        / "app"
        / "src"
        / "main"
        / "java"
        / "com"
        / "mahoraga"
        / "runtime"
        / "ModelEngineOwner.kt"
    ).read_text(encoding="utf-8")

    assert "ModelRuntimeAdmissionPolicy.isBackendAllowed(backend)" in provider
    assert "model_sha256_missing" in provider
    assert "owner.load(modelPath, backend, expectedSha256)" in provider
    assert "ModelArtifactIntegrity.verify(file, expectedSha256)" in owner
    assert "backend = Backend.CPU()" in owner


def test_native_model_runtime_enforces_actual_background_admission():
    owner = (
        ROOT
        / "android-runtime"
        / "app"
        / "src"
        / "main"
        / "java"
        / "com"
        / "mahoraga"
        / "runtime"
        / "ModelEngineOwner.kt"
    ).read_text(encoding="utf-8")
    policy = (
        ROOT
        / "android-runtime"
        / "app"
        / "src"
        / "main"
        / "java"
        / "com"
        / "mahoraga"
        / "runtime"
        / "ModelRuntimeAdmissionPolicy.kt"
    ).read_text(encoding="utf-8")

    assert "ActivityManager.getMyMemoryState(processInfo)" in owner
    assert "PowerManager).isInteractive" in owner
    assert "WorkScheduler.isEnabled(appContext)" in owner
    assert "ModelRuntimeAdmissionPolicy.isLoadAllowed(" in owner
    assert "ModelRuntimeAdmissionPolicy.isInferenceAllowed(" in owner
    assert "WorkPolicy.supportsAuthenticatedWake(android.os.Build.VERSION.SDK_INT)" in owner
    assert 'if (screenInteractive) return true' in policy
    assert 'taskClass == "background"' in policy
    assert "backgroundScheduleEnabled" in policy
    assert "screenInteractive || charging" in policy


def test_python_and_android_model_memory_overhead_stay_aligned():
    config = json.loads(
        (ROOT / "config" / "litert_model_runtime.json").read_text(encoding="utf-8")
    )
    budget = (
        ROOT
        / "android-runtime"
        / "app"
        / "src"
        / "main"
        / "java"
        / "com"
        / "mahoraga"
        / "runtime"
        / "ModelBudgetMath.kt"
    ).read_text(encoding="utf-8")

    assert config["runtime_overhead_mb"] == 1152
    assert "modelSizeMb * 1.5 + 1_152.0" in budget


def test_android_runtime_uses_agp9_builtin_kotlin_without_legacy_plugin_or_dsl():
    root_build = (ROOT / "android-runtime" / "build.gradle.kts").read_text(
        encoding="utf-8"
    )
    app_build = (ROOT / "android-runtime" / "app" / "build.gradle.kts").read_text(
        encoding="utf-8"
    )

    workflow = (
        ROOT / ".github" / "workflows" / "android-runtime-tests.yml"
    ).read_text(encoding="utf-8")

    assert 'id("com.android.application") version "9.5.3" apply false' in root_build
    assert 'classpath("org.jetbrains.kotlin:kotlin-gradle-plugin:2.4.0")' in root_build
    assert "org.jetbrains.kotlin.android" not in root_build
    assert "org.jetbrains.kotlin.android" not in app_build
    assert "kotlinOptions" not in app_build
    assert "sourceCompatibility = JavaVersion.VERSION_17" in app_build
    assert "targetCompatibility = JavaVersion.VERSION_17" in app_build
    assert 'name: Set up Gradle 9.6.0' in workflow
    assert 'gradle-version: "9.6.0"' in workflow
