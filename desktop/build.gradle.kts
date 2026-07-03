// Kotlin 2.0+ requires the separate Compose Compiler Gradle plugin
// (org.jetbrains.kotlin.plugin.compose), applied per-module below.
//
// VERSION NOTE: this Kotlin 2.0.21 / Compose Multiplatform 1.7.0 pairing is
// plausible but was NOT built in the environment that generated this repo (no
// Kotlin/Gradle toolchain there). If Gradle complains about the Compose
// compiler / Kotlin version, bump these to the current matched pair from
// https://github.com/JetBrains/compose-multiplatform/releases
plugins {
    kotlin("jvm") version "2.0.21" apply false
    kotlin("plugin.compose") version "2.0.21" apply false
    kotlin("plugin.serialization") version "2.0.21" apply false
    id("org.jetbrains.compose") version "1.7.0" apply false
}
