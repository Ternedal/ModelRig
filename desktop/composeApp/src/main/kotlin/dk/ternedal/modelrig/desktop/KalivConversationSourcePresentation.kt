package dk.ternedal.modelrig.desktop

/** Human-facing copy for persisted conversation provenance/type values. */
internal fun presentConversationSource(source: String): String = when (source.trim().lowercase()) {
    "rig" -> "Rig"
    "cloud" -> "Cloud"
    "rag" -> "Dokumenter (RAG)"
    "tools" -> "Værktøjer"
    "pending" -> "Kilde ikke afgjort"
    else -> "Kilde ukendt"
}
