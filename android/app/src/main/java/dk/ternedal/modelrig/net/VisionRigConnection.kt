package dk.ternedal.modelrig.net

import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.Interceptor
import okhttp3.OkHttpClient
import java.io.IOException
import java.util.concurrent.TimeUnit

/**
 * Which origins a paired rig service may use (ModelRig #2275: gallery
 * amendment 4 and the VisionRig transport decision 6476890811).
 *
 * HTTPS: the paired origin, any host. HTTP: only a loopback or RFC 1918 IPv4
 * literal (or `localhost`/`::1`). Plain HTTP to a Tailscale address
 * (100.64.0.0/10) is refused: remote tailnet use needs an HTTPS origin with a
 * valid certificate in front of the service. No user info, path, query or
 * fragment. The origin always comes from pairing, never from a response.
 *
 * Same rule as MediaOriginPolicy in the gallery PR (#2301); when both are on
 * main, one implementation should replace the other.
 */
object PairedOriginPolicy {
    sealed class Check {
        data class Allowed(val origin: HttpUrl) : Check()
        data class Refused(val reason: String) : Check()
    }

    fun check(raw: String?): Check {
        val text = raw?.trim().orEmpty()
        if (text.isEmpty()) return Check.Refused("Angiv adressen")
        val url = text.toHttpUrlOrNull() ?: return Check.Refused("Ugyldig adresse")
        if (url.username.isNotEmpty() || url.password.isNotEmpty() ||
            url.encodedPath != "/" || url.query != null || url.fragment != null
        ) {
            return Check.Refused("Adressen skal være en ren oprindelse, fx http://192.168.1.10:8111")
        }
        if (url.scheme == "http" && !isLoopbackOrRfc1918(url.host)) {
            return Check.Refused("Kræver HTTPS, eller en adresse på hjemmenettet (192.168.x.x, 10.x.x.x, 172.16-31.x.x)")
        }
        return Check.Allowed(url)
    }

    fun isLoopbackOrRfc1918(host: String): Boolean {
        if (host == "localhost" || host == "::1") return true
        val parts = host.split(".")
        if (parts.size != 4) return false
        val octets = parts.map { part ->
            if (part.isEmpty() || part.length > 3 || (part.length > 1 && part.startsWith("0")) ||
                !part.all(Char::isDigit)
            ) {
                return false
            }
            part.toInt().takeIf { it in 0..255 } ?: return false
        }
        val (a, b) = octets
        return a == 127 || a == 10 || (a == 172 && b in 16..31) || (a == 192 && b == 168)
    }
}

/**
 * A paired VisionRig sensor gateway. Its own token: never the ModelRig rig
 * token. [toString] never contains the token.
 */
class VisionRigConnection private constructor(val origin: HttpUrl, val token: String) {
    val gatewayUrl: String get() = origin.toString().trimEnd('/')

    override fun toString(): String = "VisionRigConnection(${origin.scheme}://${origin.host}:${origin.port})"

    companion object {
        /** VisionRigGatewayClient refuses shorter producer tokens. */
        const val MIN_TOKEN_CHARS = 32
        private const val MAX_TOKEN_CHARS = 512

        fun create(url: String?, token: String?): Result<VisionRigConnection> {
            val origin = when (val check = PairedOriginPolicy.check(url)) {
                is PairedOriginPolicy.Check.Allowed -> check.origin
                is PairedOriginPolicy.Check.Refused -> return Result.failure(VisionRigSetupException(check.reason))
            }
            val value = token?.trim().orEmpty()
            if (value.length < MIN_TOKEN_CHARS) {
                return Result.failure(VisionRigSetupException("Tokenet skal være mindst $MIN_TOKEN_CHARS tegn"))
            }
            if (value.length > MAX_TOKEN_CHARS || value.any { it.isWhitespace() || it.code !in 0x21..0x7e }) {
                return Result.failure(VisionRigSetupException("Tokenet indeholder ugyldige tegn"))
            }
            return Result.success(VisionRigConnection(origin, value))
        }
    }
}

/** A setup value was refused. The message is shown to the user and never contains the token. */
class VisionRigSetupException(message: String) : IllegalArgumentException(message)

/** A request for anything but the paired VisionRig origin was stopped before it was sent. */
class VisionRigOriginRefusedIOException(message: String) : IOException(message)

/**
 * The HTTP client every VisionRig request from the app must use. VisionRig's
 * own default is `OkHttpClient()`, which follows redirects; on a 307/308 that
 * would re-send the POST body (a camera frame) to the new host. Here
 * redirects are off, and an interceptor refuses any request outside the
 * paired origin.
 */
object VisionRigHttp {
    fun client(connection: VisionRigConnection): OkHttpClient {
        val origin = connection.origin
        return OkHttpClient.Builder()
            .connectTimeout(5, TimeUnit.SECONDS)
            .readTimeout(20, TimeUnit.SECONDS)
            .writeTimeout(20, TimeUnit.SECONDS)
            .followRedirects(false)
            .followSslRedirects(false)
            .addInterceptor(Interceptor { chain ->
                val url = chain.request().url
                if (url.scheme != origin.scheme || url.host != origin.host || url.port != origin.port) {
                    throw VisionRigOriginRefusedIOException("request outside the paired VisionRig origin refused")
                }
                val response = chain.proceed(chain.request())
                if (response.isRedirect || response.code in 300..399) {
                    response.close()
                    throw VisionRigOriginRefusedIOException("VisionRig redirect refused")
                }
                response
            })
            .build()
    }
}
