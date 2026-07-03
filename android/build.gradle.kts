// VERSION NOTE: AGP 8.5.2 / Kotlin 2.0.21 / Compose Compiler plugin 2.0.21.
// This matches the RegnSnart toolchain. Not built in the generator environment
// (no Android SDK there) — build locally. Bump versions if your installed
// Android Studio / SDK requires it.
plugins {
    id("com.android.application") version "8.5.2" apply false
    kotlin("android") version "2.0.21" apply false
    kotlin("plugin.compose") version "2.0.21" apply false
}
