package dk.ternedal.modelrig.desktop.net

import kotlinx.serialization.KSerializer

/** File-local package bridge so task request strings are encoded by kotlinx.serialization. */
internal fun String.Companion.serializer(): KSerializer<String> =
    kotlinx.serialization.serializer<String>()
