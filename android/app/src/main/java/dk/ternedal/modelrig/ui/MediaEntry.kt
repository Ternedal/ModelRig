package dk.ternedal.modelrig.ui

import android.content.Context
import android.content.Intent
import dk.ternedal.modelrig.MainActivity

/**
 * The in-app way to the generate screen (#2275 C6 G1). Before this, the generate
 * screen and the gallery were reachable only through ADB intent extras.
 *
 * The entry is shown with a paired rig, like "Opgaver" and "Personer". It needs no
 * capability call of its own: the generate screen itself says "ikke tilgængelig"
 * on a 404 or 503 and offers nothing, so the entry never claims readiness the rig
 * does not have. The generate screen reaches the gallery from a finished job.
 */
object MediaEntry {
    const val LABEL = "Medier"

    fun intent(context: Context): Intent =
        Intent(context, MainActivity::class.java).putExtra(MainActivity.EXTRA_MEDIA_GENERATE, true)
}
