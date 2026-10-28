package dk.ternedal.modelrig.ui

import dk.ternedal.modelrig.net.MediaGalleryException.Reason
import dk.ternedal.modelrig.net.MediaItem
import dk.ternedal.modelrig.net.MediaKind
import dk.ternedal.modelrig.net.MediaPage
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

/** The gallery list as the screen sees it. Pure data; no Android types. */
data class MediaGalleryState(
    val items: List<MediaItem> = emptyList(),
    val nextCursor: String? = null,
    val endReached: Boolean = false,
    val loading: Boolean = false,
    val error: Reason? = null,
    /** Items skipped by validation across all loaded pages. */
    val skipped: Int = 0,
    /** True once the first page has arrived. */
    val loaded: Boolean = false,
) {
    val canLoadMore: Boolean get() = loaded && !loading && !endReached && error == null

    /**
     * The library really is empty: nothing shown AND no further pages. A page
     * whose items were all invalid but which has a next_cursor is not empty;
     * the screen must still offer load-more (#2301 review 5684792570).
     */
    val isEmpty: Boolean get() = loaded && items.isEmpty() && endReached && error == null
}

/** Paging transitions. A refresh starts over; load-more appends and de-duplicates by ID. */
object MediaGalleryPaging {
    fun startRefresh(state: MediaGalleryState) = state.copy(loading = true, error = null)

    fun startLoadMore(state: MediaGalleryState) = state.copy(loading = true, error = null)

    fun refreshed(page: MediaPage) = MediaGalleryState(
        items = page.items,
        nextCursor = page.nextCursor,
        endReached = page.nextCursor == null,
        skipped = page.skipped,
        loaded = true,
    )

    fun appended(state: MediaGalleryState, page: MediaPage): MediaGalleryState {
        val known = state.items.mapTo(HashSet()) { it.id }
        val fresh = page.items.filter { known.add(it.id) }
        return state.copy(
            items = state.items + fresh,
            nextCursor = page.nextCursor,
            endReached = page.nextCursor == null,
            loading = false,
            skipped = state.skipped + page.skipped,
        )
    }

    /** Items already shown stay visible; the error only blocks further paging. */
    fun failed(state: MediaGalleryState, reason: Reason) = state.copy(loading = false, error = reason)
}

/** Danish user text per failure. Never includes server text, tokens or paths. */
fun mediaGalleryMessage(reason: Reason): String = when (reason) {
    Reason.NOT_PAIRED -> "Par telefonen med riggen først."
    Reason.ORIGIN_REFUSED -> "Mediebiblioteket kræver HTTPS eller en parret rig på hjemmenettet."
    Reason.UNAUTHORIZED -> "Parringen er ikke længere gyldig. Par telefonen med riggen igen."
    Reason.STORAGE_UNAVAILABLE -> "Medielageret på riggen er ikke tilgængeligt. Tjek den eksterne disk."
    Reason.BAD_REQUEST -> "Listen er forældet. Opdater for at starte forfra."
    Reason.NOT_FOUND -> "Mediet findes ikke længere."
    Reason.TOO_LARGE -> "For stort til at blive vist på telefonen."
    Reason.REDIRECT_REFUSED -> "Riggen forsøgte at viderestille forespørgslen. Den blev afvist."
    Reason.PROTOCOL -> "Riggen svarede i et format, appen ikke kender."
    Reason.NETWORK -> "Riggen kan ikke nås. Tjek at den kører, og at telefonen er på samme netværk."
    Reason.HTTP -> "Mediebiblioteket svarede med en fejl."
    Reason.UNPLAYABLE -> "Videoen kan ikke afspilles på telefonen."
}

fun skippedMessage(count: Int): String? = when {
    count <= 0 -> null
    count == 1 -> "1 medie kunne ikke vises."
    else -> "$count medier kunne ikke vises."
}

private val DATE = DateTimeFormatter.ofPattern("d. MMM yyyy, HH:mm", Locale.forLanguageTag("da-DK"))

fun mediaKindLabel(item: MediaItem): String = when (item.kind) {
    MediaKind.IMAGE -> "Billede"
    MediaKind.VIDEO -> "Video"
}

/** "1:05" or "1:02:03"; null when unknown. */
fun mediaDuration(seconds: Double?): String? {
    if (seconds == null) return null
    val total = seconds.toLong()
    val h = total / 3600
    val m = (total % 3600) / 60
    val s = total % 60
    return if (h > 0) String.format(Locale.ROOT, "%d:%02d:%02d", h, m, s)
    else String.format(Locale.ROOT, "%d:%02d", m, s)
}

/** "1,4 MB" style, decimal units as Android's own file sizes. */
fun mediaSize(bytes: Long): String {
    val locale = Locale.forLanguageTag("da-DK")
    return when {
        bytes < 1_000 -> "$bytes B"
        bytes < 1_000_000 -> String.format(locale, "%.0f kB", bytes / 1_000.0)
        bytes < 1_000_000_000 -> String.format(locale, "%.1f MB", bytes / 1_000_000.0)
        else -> String.format(locale, "%.2f GB", bytes / 1_000_000_000.0)
    }
}

fun mediaCreated(item: MediaItem, zone: ZoneId = ZoneId.systemDefault()): String =
    DATE.format(item.createdAt.atZone(zone))

/** Shown for 180°/360° or stereo media until a proper viewer exists. */
fun mediaLayoutNote(item: MediaItem): String? = if (item.isFlat) null else
    "Vises fladt: ${item.projection.replace('_', ' ')}, ${item.stereo.replace('_', ' ')}."
