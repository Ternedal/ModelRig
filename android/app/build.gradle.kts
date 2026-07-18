import java.util.Properties

plugins {
    id("com.android.application")
    kotlin("android")
    kotlin("plugin.compose")
}

// Stable signing identity across build machines/sessions. Keystore + properties
// live in the (private) repo on purpose: this is a personal, sideloaded app —
// the win is that every APK, from any session or CI, installs over the previous
// one. Keep a copy of the password in Notion Secrets as backup.
val ksProps = Properties().apply {
    val f = rootProject.file("signing/keystore.properties")
    if (f.exists()) f.inputStream().use { load(it) }
}

android {
    namespace = "dk.ternedal.modelrig"
    compileSdk = 35

    defaultConfig {
        applicationId = "dk.ternedal.modelrig"
        minSdk = 26
        targetSdk = 35
        versionCode = 246          // monotonic, bumped every release (not tied to semver)
        versionName = "1.58.113"
    }

    signingConfigs {
        create("modelrig") {
            storeFile = rootProject.file(ksProps.getProperty("storeFile") ?: "signing/modelrig.keystore")
            storePassword = ksProps.getProperty("storePassword")
            keyAlias = ksProps.getProperty("keyAlias") ?: "modelrig"
            keyPassword = ksProps.getProperty("keyPassword")
        }
    }

    buildTypes {
        debug {
            signingConfig = signingConfigs.getByName("modelrig")
        }
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("modelrig")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    buildFeatures {
        compose = true
    }
}

dependencies {
    testImplementation("junit:junit:4.13.2")
    // org.json lives in the Android framework; the unit-test stub throws on
    // every call. StreamContract parses real NDJSON, so the tests need a real
    // implementation on the JVM test classpath.
    testImplementation("org.json:json:20240303")
    // Scheduler client contracts need a real HTTP boundary without relying on
    // JDK-only com.sun.net.httpserver, which is absent from AGP's test compiler.
    testImplementation("com.squareup.okhttp3:mockwebserver:4.12.0")
    val composeBom = platform("androidx.compose:compose-bom:2024.09.03")
    implementation(composeBom)
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.activity:activity-compose:1.9.2")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.6")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")
    // Android 12+ splash. Without this the app only set windowBackground, which
    // the system splash overrides on 12+ -- so on a Pixel there was effectively
    // no branded splash. This API is the supported way to theme it.
    implementation("androidx.core:core-splashscreen:1.0.1")
}
