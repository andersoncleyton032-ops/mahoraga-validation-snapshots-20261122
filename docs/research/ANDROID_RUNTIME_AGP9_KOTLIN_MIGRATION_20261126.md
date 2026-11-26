# Android Runtime — built-in Kotlin / KGP metadata compatibility — 26/11/2026

## Findings and failed attempts

1. Public run 45801819626 on the earlier Android runtime snapshot reached Gradle and failed while applying org.jetbrains.kotlin.android: AGP 9 enables built-in Kotlin and rejects the legacy Android Kotlin plugin. PR #298 removed the root/module plugin and the legacy kotlinOptions DSL.
2. Public run 45858333659, job 140042480803, on AGP 9.5.2/Gradle 9.6.0 reached :app:compileDebugKotlin and failed. The built-in compiler was Kotlin 2.2.0 while litertlm-android:0.19.1 exposed Kotlin 2.4.0 metadata. No JUnit output or APK was produced.
3. Trial AGP 9.6.0 + Gradle 9.8.2 (public run 45859600838, job 140046846874) failed before configuration because the AGP 9.6.0 plugin marker could not be resolved from Google, Maven Central or the Plugin Portal. The official AGP API reference currently reports 9.5.3 as stable and 9.6.0 as preview alpha; treating 9.6.0 as a stable published artifact was incorrect.

## Current candidate

- Stable AGP 9.5.3.
- Gradle 9.6.0 (minimum for AGP 9.5).
- Explicit KGP 2.4.0 in the top-level buildscript dependencies classpath.
- Built-in Kotlin remains enabled; no org.jetbrains.kotlin.android plugin is applied.
- Java source/target compatibility 17, compileSdk 36 and JDK 17 remain unchanged.

The official built-in Kotlin migration guide says AGP 9.0–9.5 normally uses KGP 2.2.10 but permits selecting another supported KGP (2.2.10 or higher) by declaring org.jetbrains.kotlin:kotlin-gradle-plugin in the top-level buildscript classpath when the project does not use the Android settings plugin or another Kotlin plugin. This project does not use the Android settings plugin, KAPT or KMP. Explicit KGP 2.4.0 is the candidate to test against LiteRT-LM metadata.

## Regression contract

The Python source test checks AGP 9.5.3, KGP 2.4.0 classpath, Gradle 9.6.0 workflow, built-in plugin removal, absence of legacy kotlinOptions and Java/JVM 17.

## Validation status

IMPLEMENTED / SOURCE-CONTRACT-TEST-WRITTEN / NOT YET EXECUTED. The AGP 9.6.0 plugin resolution failure was real but belongs to the rejected trial, not this current candidate. Keep PR #299 Draft until the public Android workflow completes AGP/KGP resolution, Kotlin compilation, JUnit and APK assembly. No Realme test or installation occurred.

## Authoritative sources

- Android built-in Kotlin migration and KGP selection: https://developer.android.com/build/migrate-to-built-in-kotlin
- Android Gradle Plugin API reference (stable 9.5.3; 9.6 preview alpha): https://developer.android.com/reference/tools/gradle-api
- AGP compatibility table: https://developer.android.com/build/releases/about-agp
