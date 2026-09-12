package dk.ternedal.modelrig.desktop

/**
 * Human-facing policy for structured Agent 3 task details.
 *
 * Unknown JsonObject/JsonElement content is never serialized into primary operator copy.
 * The task surface may acknowledge that technical details exist without guessing at their meaning.
 */
internal fun presentTaskStepStructuredDetail(hasArgs: Boolean): String? =
    if (hasArgs) "Tekniske parametre skjult i oversigten" else null

internal fun presentTaskEventStructuredDetail(hasPayload: Boolean): String? =
    if (hasPayload) "Tekniske eventdetaljer skjult i oversigten" else null
