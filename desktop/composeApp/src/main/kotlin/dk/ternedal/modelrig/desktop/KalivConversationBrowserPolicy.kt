package dk.ternedal.modelrig.desktop

const val CONVERSATION_BROWSER_LABEL = "Samtaler"

/**
 * Conversation identity is part of the authority for an in-flight turn.
 *
 * Switching, clearing or deleting that identity while a request is still
 * publishing can detach callbacks from the message list/conversation they
 * belong to. An unresolved write confirmation is also bound to the turn that
 * produced it and must not be hidden behind another conversation context.
 *
 * This policy only removes local navigation authority. It never cancels a
 * worker request or resolves a confirmation remotely.
 */
data class KalivConversationBrowserPresentation(
    val contextMutationEnabled: Boolean,
    val lockMessage: String?,
)

fun presentConversationBrowser(
    busy: Boolean,
    hasPendingConfirmation: Boolean,
): KalivConversationBrowserPresentation = when {
    hasPendingConfirmation -> KalivConversationBrowserPresentation(
        contextMutationEnabled = false,
        lockMessage = "Afslut den ventende værktøjsbekræftelse før du skifter samtale.",
    )
    busy -> KalivConversationBrowserPresentation(
        contextMutationEnabled = false,
        lockMessage = "Vent på den igangværende tur før du skifter samtale.",
    )
    else -> KalivConversationBrowserPresentation(
        contextMutationEnabled = true,
        lockMessage = null,
    )
}


/**
 * Local publication order for asynchronous conversation loads.
 *
 * Capturing an epoch gives a DB read permission to publish only while no newer
 * user action has advanced the conversation context. Advancing invalidates old
 * reads; it does not cancel their IO or claim any remote mutation.
 */
class KalivConversationPublicationEpoch(initial: Long = 0L) {
    private var epoch: Long = initial

    fun capture(): Long = epoch

    fun advance(): Long {
        epoch = if (epoch == Long.MAX_VALUE) Long.MIN_VALUE else epoch + 1L
        return epoch
    }

    fun mayPublish(captured: Long): Boolean = captured == epoch
}
