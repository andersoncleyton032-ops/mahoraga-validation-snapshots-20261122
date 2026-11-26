# Android Runtime — AGP 9 built-in Kotlin migration — 26/11/2026

## Finding

Public snapshot CI run #45801819626 reached Gradle, then failed while applying `org.jetbrains.kotlin.android` to `android-runtime/app`. The exact error: AGP 9 reports that the Kotlin Android plugin is no longer required since AGP 9.0 and fails application.

The private runtime build pins AGP 9.5.2 and separately declares Kotlin Android plugin 2.4.0 at the root and app module. This is the same conflict pattern described by the official Android migration guide.

## Change

- Remove `org.jetbrains.kotlin.android` from root `android-runtime/build.gradle.kts`.
- Remove its module-level application from `android-runtime/app/build.gradle.kts`.
- Remove the legacy `android.kotlinOptions { jvmTarget = "17" }` block.
- Keep Java `sourceCompatibility` and `targetCompatibility` at 17. Built-in Kotlin's target defaults to the Android compileOptions target compatibility.
- No KAPT or Kotlin Multiplatform setup exists in this module.

AGP 9.5 uses its built-in Kotlin integration and corresponding KGP runtime dependency. The legacy 2.4.0 Android plugin version is not separately applied.

## Regression coverage

A source-contract test verifies that neither build file applies `org.jetbrains.kotlin.android`, that `kotlinOptions` is absent, and that the Java/JVM compatibility remains 17.

## Validation status

**IMPLEMENTED / TEST_ADDED / BUILD_NOT_EXECUTED.** Private Actions still fails before runner steps. The public previous run reached Gradle and exposed this conflict; this change has not yet been built. No APK installed; no device validation.

## Source

Official Android Developers migration guide: https://developer.android.com/build/migrate-to-built-in-kotlin (reviewed 26/11/2026). It states AGP 9+ enables built-in Kotlin, directs projects to remove the root/module Kotlin Android plugin, and migrate `android.kotlinOptions` to `kotlin.compilerOptions`. It also states the built-in Kotlin JVM target defaults to `android.compileOptions.targetCompatibility`.


## Follow-up: built-in Kotlin compiler metadata compatibility — 26/11/2026

The public run 45858333659 validated the initial AGP 9.5.2 migration far enough to reach :app:compileDebugKotlin, but failed: the built-in compiler reported Kotlin 2.2.0 while litertlm-android:0.19.1 classes carried Kotlin 2.4.0 metadata. Repetitive unresolved standard-library references were downstream symptoms of this metadata mismatch. No JUnit tests or APK were produced.

Official Android documentation confirms that AGP 9.0–9.5 defaults to KGP 2.2.10, while AGP 9.6 defaults to KGP 2.4.20; AGP 9.6 requires Gradle 9.8.2. The follow-up therefore upgrades AGP to 9.6.0 and the Android Runtime workflow to Gradle 9.8.2, preserving built-in Kotlin and Java/JVM 17. Source-contract assertions were extended. Build/JUnit validation remains pending; this change is based on the exact compiler error and official version matrix, not yet on a passing build.
