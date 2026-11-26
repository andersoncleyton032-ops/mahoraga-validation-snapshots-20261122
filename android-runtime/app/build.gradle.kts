plugins {
    id("com.android.application")
}

android {
    namespace = "com.mahoraga.runtime"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.mahoraga.runtime"
        minSdk = 24
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    testOptions {
        unitTests.isIncludeAndroidResources = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

}

dependencies {
    implementation("androidx.work:work-runtime:2.12.0")
    implementation("com.google.ai.edge.litertlm:litertlm-android:0.19.1")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.11.0")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20250517")
}
