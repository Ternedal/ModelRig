package dk.ternedal.modelrig.logic

/** A credential's UI-safe condition. No secret value crosses this boundary. */
enum class CredentialCondition {
    MISSING,
    READY,
    INVALID,
}

/** Where the app should go after the splash screen. */
enum class AppEntryDestination {
    CHAT,
    SETUP,
}

/**
 * One immutable snapshot of the configured chat sources.
 *
 * Compose previously rebuilt this decision from several booleans. Keeping the
 * policy here prevents an unreadable credential from being treated differently
 * by splash, setup and later screens.
 */
data class SourceAvailability(
    val rig: CredentialCondition,
    val cloud: CredentialCondition,
) {
    val canChat: Boolean
        get() = rig == CredentialCondition.READY || cloud == CredentialCondition.READY

    val hasInvalidCredentials: Boolean
        get() = rig == CredentialCondition.INVALID || cloud == CredentialCondition.INVALID

    val entryDestination: AppEntryDestination
        get() = if (canChat) AppEntryDestination.CHAT else AppEntryDestination.SETUP

    companion object {
        fun from(
            rig: StoredCredentialRead,
            cloud: StoredCredentialRead,
        ): SourceAvailability = SourceAvailability(
            rig = rig.toCondition(),
            cloud = cloud.toCondition(),
        )
    }
}

private fun StoredCredentialRead.toCondition(): CredentialCondition = when (this) {
    StoredCredentialRead.Missing -> CredentialCondition.MISSING
    is StoredCredentialRead.Ready -> CredentialCondition.READY
    StoredCredentialRead.Invalid -> CredentialCondition.INVALID
}
