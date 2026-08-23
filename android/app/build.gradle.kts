import org.jetbrains.kotlin.gradle.dsl.JvmTarget

import java.util.Properties

plugins {
    id("com.android.application")
    kotlin("android")
    kotlin("plugin.compose")
    id("io.github.takahirom.roborazzi")
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
        versionCode = 292          // monotonic, bumped every release (not tied to semver)
        versionName = "2.0.11"
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
        create("a425f") {
            // Dedicated physical-test app identity. It installs next to normal
            // Kaliv and therefore owns a separate app sandbox, SharedPreferences
            // and AndroidKeyStore namespace. No product pairing state is reused.
            initWith(getByName("debug"))
            applicationIdSuffix = ".a425f"
            versionNameSuffix = "-a425f"
            isDebuggable = true
            matchingFallbacks += listOf("debug")
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
        buildConfig = true
        compose = true
    }
}

// Kotlin 2.4 fjernede 'kotlinOptions { jvmTarget = "17" }'. Samme maal, ny DSL.
kotlin {
    compilerOptions {
        jvmTarget.set(JvmTarget.JVM_17)
    }
}

android.testOptions {
    unitTests {
        // Robolectric skal bruge rigtige ressourcer (temaer, fonte) til screenshots.
        isIncludeAndroidResources = true
    }
}

roborazzi {
    // Baselines bor i traeet og reviewes som enhver anden diff.
    outputDir.set(layout.projectDirectory.dir("src/test/screenshots"))
}

dependencies {
    // QR-parring. To afhaengigheder, begge bevidst valgt smaa:
    //  * zxing core er ren Java uden Android- eller Play Services-binding, og
    //    SAMME artefakt kan baade laese og skrive QR — rig-siden kan bruge den
    //    til at TEGNE koden, telefonen til at laese den.
    //  * CameraX giver et livscyklus-bundet kamera uden at vi skal skrive
    //    Camera2-state selv. Vi tager kun de fire moduler vi bruger.
    implementation("com.google.zxing:core:3.5.3")
    implementation("androidx.camera:camera-core:1.4.2")
    implementation("androidx.camera:camera-camera2:1.4.2")
    implementation("androidx.camera:camera-lifecycle:1.4.2")
    implementation("androidx.camera:camera-view:1.4.2")
    testImplementation("junit:junit:4.13.2")
    // Screenshot-regression: Robolectric 4.16 (SDK 36 + JDK 21) + Roborazzi.
    testImplementation("org.robolectric:robolectric:4.16.1")
    testImplementation("io.github.takahirom.roborazzi:roborazzi:1.70.0")
    testImplementation("io.github.takahirom.roborazzi:roborazzi-compose:1.70.0")
    testImplementation(platform("androidx.compose:compose-bom:2026.06.01"))
    testImplementation("androidx.compose.ui:ui-test-junit4")
    testImplementation("androidx.test.ext:junit:1.3.0")
    debugImplementation("androidx.compose.ui:ui-test-manifest")
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
