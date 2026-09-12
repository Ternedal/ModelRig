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
