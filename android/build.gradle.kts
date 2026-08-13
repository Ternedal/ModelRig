// VERSION NOTE: AGP 8.5.2 / Kotlin 2.0.21 / Compose Compiler plugin 2.0.21.
// This matches the RegnSnart toolchain. Not built in the generator environment
// (no Android SDK there) — build locally. Bump versions if your installed
// Android Studio / SDK requires it.
plugins {
    id("com.android.application") version "9.3.1" apply false
    kotlin("android") version "2.4.10" apply false
    kotlin("plugin.compose") version "2.4.10" apply false
    // Screenshot-regression (DDR-001 fase 1): Roborazzi paa Robolectric — JVM,
    // ingen emulator. Version verificeret mod AGP 8.9/Kotlin 2.4 13/08-2026.
    id("io.github.takahirom.roborazzi") version "1.70.0" apply false
}
