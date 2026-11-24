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
 * What the preset row has to say about its store, as two independent facts.
 *
 * [loadFailed] is about the list on screen: it is not the store's, and it stays
 * so until a reload succeeds. [mutation] is about the last save or delete the
 * user attempted. One nullable field for both let a failed save replace a
 * failed load, and closing the form then cleared the only thing left -- the row
 * went back to looking like a store with no presets in it.
 */
internal data class PresetErrorState(
    val loadFailed: Boolean = false,
    val mutation: PresetStoreOperation? = null,
) {
    init {
        require(mutation != PresetStoreOperation.LOAD) { "a failed load is loadFailed, not a mutation" }
    }

    /**
     * A mutation that failed says so and leaves the load state alone: nothing was
     * read. A mutation that succeeded was followed by a reload, and that reload
     * is the newest word on whether the list is the store's.
     */
    fun afterMutation(outcome: PresetMutationOutcome): PresetErrorState =
        if (!outcome.mutated) copy(mutation = outcome.error)
        else PresetErrorState(loadFailed = outcome.presets == null, mutation = null)

    /** Opening or closing the save form dismisses the last attempt, never the load state. */
    fun afterFormToggle(): PresetErrorState = copy(mutation = null)

    /** The sentences to show, the standing condition first. */
    val messages: List<String>
        get() = listOfNotNull(
            if (loadFailed) presentPresetStoreError(PresetStoreOperation.LOAD) else null,
            mutation?.let(::presentPresetStoreError),
        )
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
