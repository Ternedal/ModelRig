package dk.ternedal.modelrig.ui.chat

import dk.ternedal.modelrig.net.MediaJobRef
import dk.ternedal.modelrig.net.MediaRefusal

/**
 * The line under an answer when the rig refused a picture or a clip the model asked for.
 *
 * Rig 20/11: the refusal reached the user only in the model's words ("der er tekniske
 * problemer med billedgenerering"), which said neither why nor what to do. This says
 * both, from the rig's own code, and keeps the code visible so it can be reported.
 *
 * Pure: no Compose, no network. A turn that queued a job after all (the model called
 * again and it worked) gets no notice -- the bubble is the answer.
 */
object MediaRefusalNotice {
    /** Null when there is nothing to say: no refusal, or a job was queued in the same turn. */
    fun text(refusals: List<MediaRefusal>, queuedJobs: Int): String? {
        if (queuedJobs > 0) return null
        val last = refusals.lastOrNull() ?: return null
        val what = if (last.kind == MediaJobRef.Kind.VIDEO) "videoen" else "billedet"
        val sentence = when (last.code) {
            "owner_limit", "queue_full" ->
                "Riggen er optaget med andre job. Bed om $what igen, n\u00e5r et af dem er f\u00e6rdigt."
            "invalid_arguments", "invalid_request", "profile_not_enabled", "source_not_understood" ->
                "Riggen kunne ikke bruge det, modellen bad om. Pr\u00f8v at bede om $what igen."
            "no_source_image", "source_job_not_found", "source_job_not_completed", "source_not_found",
            "source_not_an_image", "source_profile_not_enabled" ->
                "Der er ikke et f\u00e6rdigt billede at lave video af endnu."
            else -> "Riggen lavede ikke $what."
        }
        return "$sentence (${last.code})"
    }
}
