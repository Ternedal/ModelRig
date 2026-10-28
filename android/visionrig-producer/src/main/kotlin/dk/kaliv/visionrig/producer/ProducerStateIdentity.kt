package dk.kaliv.visionrig.producer

import java.security.MessageDigest
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import okhttp3.HttpUrl.Companion.toHttpUrl

private val stateIdentityJson = Json {
    encodeDefaults = true
    explicitNulls = false
}

data class ProducerStateIdentity(
    val gatewayUrl: String,
    val sourceId: String,
    val sourceType: String,
) {
    init {
        require(sourceId.isNotBlank())
        require(sourceType in setOf("camera", "screen", "vr", "image"))
    }

    fun key(): String {
        val parsed = gatewayUrl.toHttpUrl()
        require(parsed.username.isEmpty() && parsed.password.isEmpty()) {
            "gateway URL must not contain credentials"
        }
        require(parsed.query == null && parsed.fragment == null) {
            "gateway URL must not contain query or fragment"
        }
        val normalizedGateway = parsed.toString().trimEnd('/')
        val canonical = stateIdentityJson.encodeToString(
            linkedMapOf(
                "gateway_url" to normalizedGateway,
                "source_id" to sourceId,
                "source_type" to sourceType,
            )
        )
        val digest = MessageDigest.getInstance("SHA-256")
            .digest(canonical.toByteArray(Charsets.UTF_8))
            .joinToString("") { byte -> "%02x".format(byte) }
        return "producer-" + digest
    }

    fun defaultStateFileName(): String = key() + ".json"
}
