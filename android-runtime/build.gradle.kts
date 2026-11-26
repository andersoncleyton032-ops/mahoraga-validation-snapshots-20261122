buildscript {
    repositories {
        google()
        mavenCentral()
    }
    dependencies {
        // AGP 9.5.x built-in Kotlin defaults to KGP 2.2.10. LiteRT-LM
        // 0.19.1 emits Kotlin 2.4.0 metadata, so pin the supported KGP
        // version explicitly without applying the legacy kotlin-android plugin.
        classpath("org.jetbrains.kotlin:kotlin-gradle-plugin:2.4.0")
    }
}

plugins {
    id("com.android.application") version "9.5.3" apply false
}
