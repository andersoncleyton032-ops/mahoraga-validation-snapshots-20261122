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
