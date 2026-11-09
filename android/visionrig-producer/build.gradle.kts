// VisionRig's Kaliv producer, vendored byte-for-byte from one VisionRig SHA
// (VENDORED_FROM.json; ModelRig #2275, decision 6478056078). Never edit the
// sources here: re-vendor with scripts/sync_visionrig_producer.py, and
// tests/workflow_visionrig_vendored_producer.py fails on any drift.
plugins {
    id("com.android.library")
    kotlin("plugin.serialization")
}

android {
    namespace = "dk.kaliv.visionrig.vendored"
    compileSdk = 37
    defaultConfig {
        minSdk = 26
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

dependencies {
    // Exactly the versions the app already resolves, so the vendored code
    // upgrades nothing (CameraX stays 1.4.2: the QR scanner is untouched).
    // VisionRig itself builds against CameraX 1.6.2; the adapter compiles and
    // its tests pass against 1.4.2, a physical capture test is still due.
    implementation("androidx.camera:camera-core:1.4.2")
    implementation("androidx.camera:camera-lifecycle:1.4.2")
    implementation("androidx.core:core-ktx:1.18.0")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.6")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-core:1.11.0")
    // The one new library: the producer persists its state as JSON
    // (@Serializable). 1.11.0, not 1.12.0 (under two weeks old on 28 Oct 2026).
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.11.0")
    // VisionRigGatewayClient takes an OkHttpClient: the app injects its own.
    api("com.squareup.okhttp3:okhttp:5.5.0")
}
