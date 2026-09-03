// Kotlin 2.0+ requires the separate Compose Compiler Gradle plugin
// (org.jetbrains.kotlin.plugin.compose), applied per-module below.
//
// Keep Kotlin JVM, Compose Compiler and serialization on the same Kotlin
// release. Compose Multiplatform is versioned independently; exact-head CI is
// the compatibility authority for this repository.
plugins {
    kotlin("jvm") version "2.4.10" apply false
    kotlin("plugin.compose") version "2.4.10" apply false
    kotlin("plugin.serialization") version "2.4.10" apply false
    id("org.jetbrains.compose") version "1.12.0" apply false
}
