package dk.ternedal.modelrig.desktop

internal enum class KalivConversationBrowserFailure {
    LOAD,
    RENAME,
    COPY,
    DELETE,
}

/** Human-facing copy for local conversation-browser failures. */
internal fun presentConversationBrowserFailure(failure: KalivConversationBrowserFailure): String = when (failure) {
    KalivConversationBrowserFailure.LOAD -> "Kunne ikke hente samtaler."
    KalivConversationBrowserFailure.RENAME -> "Kunne ikke omdøbe samtalen."
    KalivConversationBrowserFailure.COPY -> "Kunne ikke kopiere samtalen."
    KalivConversationBrowserFailure.DELETE -> "Kunne ikke slette samtalen."
}
