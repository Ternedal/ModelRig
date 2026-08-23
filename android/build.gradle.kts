// Android toolchain: AGP 9.3.1 + Gradle 9.6.1 with AGP built-in Kotlin.
// Compose Compiler remains explicitly aligned to Kotlin 2.4.10. Exact-head CI
// is the compatibility authority for this repository.
plugins {
    id("com.android.application") version "9.3.1" apply false
    kotlin("plugin.compose") version "2.4.10" apply false
    // Screenshot-regression (DDR-001 fase 1): Roborazzi paa Robolectric — JVM,
    // ingen emulator. Roborazzi 1.56.0+ supports AGP 9; this repo uses 1.70.0.
    id("io.github.takahirom.roborazzi") version "1.70.0" apply false
}
