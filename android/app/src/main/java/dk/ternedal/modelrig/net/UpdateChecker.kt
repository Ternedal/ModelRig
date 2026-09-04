package dk.ternedal.modelrig.net

import okhttp3.OkHttpClient
import okhttp3.Request
import java.util.concurrent.TimeUnit

/**
 * In-app-opdateringstjek mod GitHub-releases — uden API og uden token.
 * /releases/latest svarer med en redirect til /releases/tag/vX.Y.Z; vi
 * laeser versionen af Location-headeren (followRedirects=false), saa
 * GitHub-API'ets rate-limit aldrig er i vejen. APK'en hentes fra den
 * stabile /releases/latest/download/kaliv-latest.apk. Blocking OkHttp —
 * kald altid fra Dispatchers.IO (samme kontrakt som ModelRigClient).
 */
object UpdateChecker {
    const val APK_URL =
        "https://github.com/Ternedal/ModelRig/releases/latest/download/kaliv-latest.apk"
    private const val LATEST_URL = "https://github.com/Ternedal/ModelRig/releases/latest"

    private val client = OkHttpClient.Builder()
        .followRedirects(false)
        .connectTimeout(6, TimeUnit.SECONDS)
        .readTimeout(6, TimeUnit.SECONDS)
        .build()

    /** Nyeste udgivne version ("2.0.0") eller null hvis tjekket fejler. */
    fun latestVersion(): String? {
        val res = runCatching {
            client.newCall(Request.Builder().url(LATEST_URL).head().build()).execute()
        }.getOrNull() ?: return null
        res.use {
            val loc = it.header("Location") ?: return null
            val tag = loc.substringAfterLast("/tag/", missingDelimiterValue = "")
            if (tag.isEmpty()) return null
            return tag.removePrefix("v").trim().ifEmpty { null }
        }
    }

    /**
     * Strengt hoejere semver (major.minor.patch) — samme semantik som
     * Windows-updaterens isNewer. Misdannede versioner tilbydes aldrig.
     */
    fun isNewer(current: String, latest: String): Boolean {
        val c = parse(current) ?: return false
        val l = parse(latest) ?: return false
        for (i in 0..2) {
            if (l[i] > c[i]) return true
            if (l[i] < c[i]) return false
        }
        return false
    }

    private fun parse(v: String): IntArray? {
        val parts = v.removePrefix("v").trim().split(".")
        if (parts.size != 3) return null
        val nums = IntArray(3)
        for (i in 0..2) nums[i] = parts[i].toIntOrNull() ?: return null
        return nums
    }
}
