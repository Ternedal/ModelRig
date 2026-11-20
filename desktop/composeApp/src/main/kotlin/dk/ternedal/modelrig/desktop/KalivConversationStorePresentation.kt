package dk.ternedal.modelrig.desktop

import dk.ternedal.modelrig.desktop.data.DesktopChatDb

/**
 * #973 (#779 pkt. 8): the conversation browser's storage failures as human copy.
 *
 * Two defects this closes: (1) a failed initial load used to become an empty
 * list, indistinguishable from "no conversations"; (2) rename/copy/delete
 * failures showed `Throwable.message` verbatim. Neither is operator copy. Every
 * failure is now one of four fixed sentences chosen by the *operation* that
 * failed, never by the exception's text -- a SQLite path, a lock name or a JDBC
 * detail belongs in the log, not in the panel.
 */
enum class ConversationStoreOperation { LOAD, RENAME, COPY, DELETE }

internal fun presentConversationStoreError(operation: ConversationStoreOperation): String = when (operation) {
    ConversationStoreOperation.LOAD -> "Samtalerne kunne ikke indlæses fra den lokale database"
    ConversationStoreOperation.RENAME -> "Samtalen kunne ikke omdøbes"
    ConversationStoreOperation.COPY -> "Samtalen kunne ikke kopieres"
    ConversationStoreOperation.DELETE -> "Samtalen kunne ikke slettes"
}

/** The browser's list state: loaded (possibly empty) or failed -- never an empty list standing in for a failure. */
sealed class ConversationListState {
    abstract val conversations: List<DesktopChatDb.ConvMeta>

    data class Loaded(override val conversations: List<DesktopChatDb.ConvMeta>) : ConversationListState()

    data object Failed : ConversationListState() {
        override val conversations: List<DesktopChatDb.ConvMeta> get() = emptyList()
    }
}

/** Wraps a load so that a storage failure is a state, not an empty list. */
internal fun loadConversationList(load: () -> List<DesktopChatDb.ConvMeta>): ConversationListState =
    runCatching { ConversationListState.Loaded(load()) }.getOrElse { ConversationListState.Failed }
