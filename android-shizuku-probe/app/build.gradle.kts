plugins {
    id("com.android.application")
}

android {
    namespace = "com.mahoraga.shizukuprobe"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.mahoraga.shizukuprobe"
        minSdk = 26
        targetSdk = 36
        versionCode = 1
        versionName = "0.2.0-alpha1"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

dependencies {
    implementation("dev.rikka.shizuku:api:13.1.5")
    implementation("dev.rikka.shizuku:provider:13.1.5")
    testImplementation("junit:junit:4.13.2")
}
