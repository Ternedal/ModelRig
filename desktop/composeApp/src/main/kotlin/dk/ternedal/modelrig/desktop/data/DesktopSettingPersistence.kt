package dk.ternedal.modelrig.desktop.data

sealed interface DesktopSettingSaveResult {
    data object Saved : DesktopSettingSaveResult
    data class Failed(val userMessage: String) : DesktopSettingSaveResult
}

/**
 * Small, UI-independent boundary around setting writes.
 *
 * A storage/DPAPI exception must never be mistaken for a successful save,
 * and neither the attempted value nor the exception text is suitable for UI:
 * both can contain credential material or machine-specific details.
 */
object DesktopSettingPersistence {
    private val credentialKeys = setOf("deviceToken", "cloudKey")

    fun save(
        key: String,
        value: String,
        writer: (String, String) -> Unit,
    ): DesktopSettingSaveResult = try {
        writer(key, value)
        DesktopSettingSaveResult.Saved
    } catch (_: Exception) {
        DesktopSettingSaveResult.Failed(
            if (key in credentialKeys) {
                "Credential kunne ikke gemmes sikkert. Den tidligere værdi bruges stadig."
            } else {
                "Indstillingen kunne ikke gemmes. Den tidligere værdi bruges stadig."
            },
        )
    }
}
