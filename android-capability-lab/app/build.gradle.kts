plugins {
    id("com.android.application")
}

android {
    namespace = "com.mahoraga.capabilitylab"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.mahoraga.capabilitylab"
        minSdk = 26
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }


}

dependencies {
    testImplementation("junit:junit:4.13.2")
    // Local JVM tests need a real JSON implementation; android.jar exposes stub methods.
    testImplementation("org.json:json:20260814")
}
