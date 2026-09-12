package dk.ternedal.modelrig.desktop

import dk.ternedal.modelrig.desktop.net.ChatResult
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse

class KalivChatTurnConfigTest {
    private fun config(
        localModel: String = "local-a",
        cloudModel: String = "cloud-a",
        preferLocal: Boolean = true,
    ) = KalivChatTurnConfig(
        localUrl = "http://local-a",
        localPath = "/api/chat-a",
        localModel = localModel,
        deviceToken = "device-secret-a",
        cloudKey = "cloud-secret-a",
        cloudModel = cloudModel,
        localSystem = "local-system-a",
        cloudSystem = "cloud-system-a",
        preferLocal = preferLocal,
        autoCloudFallback = true,
        toolsMode = false,
        ragMode = true,
        ragSourceFilter = "docs-a",
    )

    @Test
    fun capturedConfigDoesNotFollowLaterSettingVariables() {
        var localUrl = "http://local-a"
        var localModel = "local-a"
        var cloudModel = "cloud-a"
        val captured = KalivChatTurnConfig(
            localUrl = localUrl,
            localPath = "/api/chat-a",
            localModel = localModel,
            deviceToken = "device-secret-a",
            cloudKey = "cloud-secret-a",
            cloudModel = cloudModel,
            localSystem = "local-system-a",
            cloudSystem = "cloud-system-a",
            preferLocal = true,
            autoCloudFallback = true,
            toolsMode = false,
            ragMode = false,
            ragSourceFilter = null,
        )

        localUrl = "http://local-b"
        localModel = "local-b"
        cloudModel = "cloud-b"

        assertEquals("http://local-a", captured.localUrl)
        assertEquals("local-a", captured.localModel)
        assertEquals("cloud-a", captured.cloudModel)
    }

    @Test
    fun provenanceUsesModelsFromCapturedTurn() {
        val captured = config(localModel = "local-at-send", cloudModel = "cloud-at-send")
        assertEquals("local-at-send", captured.completedProvenance(ChatResult.Source.LOCAL).model)
        assertEquals("cloud-at-send", captured.completedProvenance(ChatResult.Source.CLOUD).model)
    }

    @Test
    fun ragMetadataUsesCapturedLocalModelEvenWhenCloudIsPreferred() {
        val captured = config(localModel = "rag-local", cloudModel = "cloud-preferred", preferLocal = false)
        assertEquals("rag-local", captured.ragConversationModel())
    }

    @Test
    fun credentialsAreNotExposedByDefaultStringRepresentation() {
        val captured = config()
        assertFalse(captured.toString().contains("device-secret-a"))
        assertFalse(captured.toString().contains("cloud-secret-a"))
    }
}
