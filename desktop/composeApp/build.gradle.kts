import org.jetbrains.compose.desktop.application.dsl.TargetFormat

plugins {
    kotlin("jvm")
    kotlin("plugin.compose")
    kotlin("plugin.serialization")
    id("org.jetbrains.compose")
}

repositories {
    google()
    mavenCentral()
    maven("https://maven.pkg.jetbrains.space/public/p/compose/dev")
}

dependencies {
    implementation(compose.desktop.currentOs)
    implementation(compose.material3)
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.3")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-core:1.9.0")
    // SQLite-first, per project convention. Android uses its built-in SQLite;
    // plain JVM needs an explicit embedded driver -- this is that driver, not a
    // server (no network, single file, no separate process). Version verified
    // against Maven Central 2026-07-04.
    implementation("org.xerial:sqlite-jdbc:3.49.1.0")
}

compose.desktop {
    application {
        mainClass = "dk.ternedal.modelrig.desktop.MainKt"
        nativeDistributions {
            // Only Deb declared: this project ships desktop as OS-native UBER
            // JARS (packageUberJarForCurrentOS in CI), never native installers.
            // Dmg/Msi were template leftovers -- and Dmg's config-time
            // validation rejects any 0.x version outright (verified locally),
            // which forced the jar filenames to lie about the app version
            // ("1.0.0" on every release). Deb accepts 0.x, so keeping just it
            // lets packageVersion tell the truth.
            targetFormats(TargetFormat.Deb)
            packageName = "ModelRig"
            packageVersion = "1.10.1"
        }
    }
}

kotlin {
    jvmToolchain(21)
}
