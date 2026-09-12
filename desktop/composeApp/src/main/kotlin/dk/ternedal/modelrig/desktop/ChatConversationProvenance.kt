package dk.ternedal.modelrig.desktop

import dk.ternedal.modelrig.desktop.net.ChatResult

/**
 * Conversation-level provenance for normal desktop Chat.
 *
 * `source/model` means the latest successfully completed normal-chat answer.
 * A newly created normal conversation is deliberately unresolved until a route
 * actually answers, so a failed preferred route is never persisted as fact.
 */
internal data class ChatConversationProvenance(
    val source: String,
    val model: String,
)

internal val PendingChatConversationProvenance = ChatConversationProvenance(
    source = "pending",
    model = "",
)

internal fun completedChatConversationProvenance(
    source: ChatResult.Source,
    localModel: String,
    cloudModel: String,
): ChatConversationProvenance = when (source) {
    ChatResult.Source.LOCAL -> ChatConversationProvenance(source = "rig", model = localModel)
    ChatResult.Source.CLOUD -> ChatConversationProvenance(source = "cloud", model = cloudModel)
}
