package dk.ternedal.modelrig.voice

import android.content.Context
import com.google.android.gms.cast.framework.CastOptions
import com.google.android.gms.cast.framework.OptionsProvider
import com.google.android.gms.cast.framework.SessionProvider

/**
 * Google Cast SDK discovers this provider from the manifest.
 *
 * The custom receiver ID must be provisioned by the operator; there is no
 * hardcoded development receiver or implicit fallback to Default Media Receiver.
 */
class KalivCastOptionsProvider : OptionsProvider {
    override fun getCastOptions(context: Context): CastOptions {
        val appId = context.getSharedPreferences("kaliv_cast", Context.MODE_PRIVATE)
            .getString("receiver_app_id", null)
            ?.trim()
            .orEmpty()
        // Cast SDK requires an app ID at initialization. A missing ID uses the
        // platform example ID for SDK startup only; app UI must keep casting
        // disabled until a real custom receiver ID has been configured.
        return CastOptions.Builder()
            .setReceiverApplicationId(if (appId.isNotBlank()) appId else "CC1AD845")
            .build()
    }

    override fun getAdditionalSessionProviders(context: Context): List<SessionProvider> = emptyList()
}
