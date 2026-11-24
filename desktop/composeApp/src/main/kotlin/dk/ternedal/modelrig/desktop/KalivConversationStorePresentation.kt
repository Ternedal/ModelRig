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

/** Same rule for the system-instruction presets (follow-up noted on #2451). */
enum class PresetStoreOperation { LOAD, SAVE, DELETE }

internal fun presentPresetStoreError(operation: PresetStoreOperation): String = when (operation) {
    PresetStoreOperation.LOAD -> "Forudindstillingerne kunne ikke indlæses fra den lokale database"
    PresetStoreOperation.SAVE -> "Forudindstillingen kunne ikke gemmes"
    PresetStoreOperation.DELETE -> "Forudindstillingen kunne ikke slettes"
}

/**
 * A preset mutation followed by the reload that shows its result, with the two
 * failures kept apart. Wrapping both in one `runCatching` reported a save that
 * had succeeded as "could not be saved" whenever the reload after it failed:
 * the form stayed open, and `savePreset` is a plain INSERT, so a second press
 * stored the preset twice.
 *
 * - the mutation fails: nothing changed, the error names the mutation;
 * - the mutation succeeds and the reload fails: [mutated] is true, the error is
 *   LOAD, and [presets] is null -- the caller keeps what it shows;
 * - both succeed: the fresh list and no error.
 */
internal data class PresetMutationOutcome(
    val mutated: Boolean,
    val presets: List<DesktopChatDb.PresetMeta>?,
    val error: PresetStoreOperation?,
)

internal fun mutatePresetsThenReload(
    operation: PresetStoreOperation,
    mutate: () -> Unit,
    reload: () -> List<DesktopChatDb.PresetMeta>,
): PresetMutationOutcome {
    if (runCatching(mutate).isFailure) return PresetMutationOutcome(mutated = false, presets = null, error = operation)
    val reloaded = runCatching(reload)
    return PresetMutationOutcome(
        mutated = true,
        presets = reloaded.getOrNull(),
        error = if (reloaded.isFailure) PresetStoreOperation.LOAD else null,
    )
}

/**
 * Opening or closing the save form dismisses a failed save or delete -- the user
 * has moved on from that attempt. It never dismisses a failed load: the list on
 * screen is still not the store's, and only a reload that succeeds changes that.
 */
internal fun presetErrorAfterFormToggle(current: PresetStoreOperation?): PresetStoreOperation? =
    current.takeIf { it == PresetStoreOperation.LOAD }

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
