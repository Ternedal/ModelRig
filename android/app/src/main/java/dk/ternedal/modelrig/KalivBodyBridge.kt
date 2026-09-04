package dk.ternedal.modelrig

import android.content.Context
import android.content.Intent

/**
 * The bridge to Kaliv Body, the separate Unity renderer app (slice D, host
 * choice taken 4/9: standalone app first, Unity as a Library later if wanted).
 *
 * Kaliv already holds a paired device token. Handing it to Kaliv Body as
 * intent extras means the body app never pairs on its own; BodyRigRigLink
 * on the Unity side reads exactly these two extras first. The intent is
 * the package's own launch intent, pinned to that package, so the token
 * goes to Kaliv Body and nothing else on the device.
 */
object KalivBodyBridge {
    const val PACKAGE = "dk.ternedal.kalivbody"
    const val EXTRA_RIG_URL = "bodyrig_rig_url"
    const val EXTRA_RIG_TOKEN = "bodyrig_rig_token"

    /** A launch intent carrying the rig, or null when Kaliv Body is not installed. */
    fun launchIntent(context: Context, baseUrl: String, token: String): Intent? =
        carry(context.packageManager.getLaunchIntentForPackage(PACKAGE), baseUrl, token)

    /**
     * Pin the app's launch intent to its package and add the rig. Null when
     * there is no launch intent (app absent) or nothing to hand over.
     */
    fun carry(launch: Intent?, baseUrl: String, token: String): Intent? {
        if (launch == null || baseUrl.isBlank() || token.isBlank()) return null
        launch.setPackage(PACKAGE)
        launch.putExtra(EXTRA_RIG_URL, baseUrl.trimEnd('/'))
        launch.putExtra(EXTRA_RIG_TOKEN, token)
        launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        return launch
    }
}
