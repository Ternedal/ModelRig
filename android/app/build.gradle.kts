import org.jetbrains.kotlin.gradle.dsl.JvmTarget

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
    compileSdk = 36

    defaultConfig {
        applicationId = "dk.ternedal.modelrig"
        minSdk = 26
        targetSdk = 35
        versionCode = 278          // monotonic, bumped every release (not tied to semver)
        versionName = "1.58.151"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
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
    buildFeatures {
        compose = true
    }
}

// Kotlin 2.4 fjernede 'kotlinOptions { jvmTarget = "17" }'. Samme maal, ny DSL.
kotlin {
    compilerOptions {
        jvmTarget.set(JvmTarget.JVM_17)
    }
}

dependencies {
    testImplementation("junit:junit:4.13.2")
    // org.json lives in the Android framework; the unit-test stub throws on
    // every call. StreamContract parses real NDJSON, so the tests need a real
    // implementation on the JVM test classpath.
    testImplementation("org.json:json:20260719")
    // Scheduler client contracts need a real HTTP boundary without relying on
    // JDK-only com.sun.net.httpserver, which is absent from AGP's test compiler.
    testImplementation("com.squareup.okhttp3:mockwebserver:5.4.0")
    val composeBom = platform("androidx.compose:compose-bom:2026.06.01")
    implementation(composeBom)
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.activity:activity-compose:1.13.0")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.6")
    implementation("com.squareup.okhttp3:okhttp:5.4.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.11.0")
    // Android 12+ splash. Without this the app only set windowBackground, which
    // the system splash overrides on 12+ -- so on a Pixel there was effectively
    // no branded splash. This API is the supported way to theme it.
    implementation("androidx.core:core-splashscreen:1.2.0")

    // T-044 Control Center UI/accessibility gate. These tests run on a real
    // API-35 emulator in CI because Compose's Accessibility Test Framework
    // integration requires API 34+ and is not supported by Robolectric.
    androidTestImplementation(composeBom)
    androidTestImplementation("androidx.compose.ui:ui-test-junit4")
    androidTestImplementation("androidx.compose.ui:ui-test-junit4-accessibility")
    androidTestImplementation("androidx.test.ext:junit:1.3.0")
    androidTestImplementation("androidx.test:runner:1.7.0")
    debugImplementation("androidx.compose.ui:ui-test-manifest")
}
