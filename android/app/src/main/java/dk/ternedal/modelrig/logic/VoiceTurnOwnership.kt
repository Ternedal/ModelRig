package dk.ternedal.modelrig.logic

/**
 * A voice result belongs to the conversation and navigation generation that
 * initiated it. Checking the conversation ID alone misses A -> B -> A changes.
 *
 * Pure policy: caller owns the immutable turn snapshot and checks this before
 * persisting a completed result. This is not a DB lock or a network cancel.
 */
internal fun mayPersistCompletedVoiceTurn(
    originalConversationId: Long?,
    selectedConversationId: Long?,
    originalNavigationRevision: Int,
    currentNavigationRevision: Int,
    playbackStopped: Boolean,
): Boolean =
    !playbackStopped &&
        originalConversationId == selectedConversationId &&
        originalNavigationRevision == currentNavigationRevision
