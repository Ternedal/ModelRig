package dk.ternedal.modelrig.net

import org.json.JSONException
import org.json.JSONObject

/**
 * Which media kinds the rig offers: `kaliv-media-capabilities/v1`, a design
 * target (docs/contracts/kaliv-media-job-v1). Where the route lives is ChatGPT's.
 *
 * DEN BÆRENDE REGEL er den modsatte af [WorkerCapabilities]: medier er slået fra
 * som standard og høj-risiko, så en art tilbydes KUN når riggen udtrykkeligt
 * har sagt `true`. Manglende, ulæseligt, et andet schema eller en ikke-boolean
 * betyder slået fra. Et mislykket probe kan aldrig tænde noget.
 */
data class MediaCapabilities(
    val textToImage: Boolean,
    val textToVideo: Boolean,
    val imageToVideo: Boolean,
) {
    val any: Boolean get() = textToImage || textToVideo || imageToVideo

    companion object {
        const val SCHEMA = "kaliv-media-capabilities/v1"

        /** Nothing offered: the answer before, or instead of, a readable probe. */
        val NONE = MediaCapabilities(textToImage = false, textToVideo = false, imageToVideo = false)

        fun parse(body: String?): MediaCapabilities {
            if (body.isNullOrBlank()) return NONE
            val obj = try {
                JSONObject(body)
            } catch (e: JSONException) {
                return NONE
            }
            if (obj.opt("schema") != SCHEMA) return NONE
            fun on(key: String) = obj.opt(key) == true
            return MediaCapabilities(on("text_to_image"), on("text_to_video"), on("image_to_video"))
        }
    }
}
