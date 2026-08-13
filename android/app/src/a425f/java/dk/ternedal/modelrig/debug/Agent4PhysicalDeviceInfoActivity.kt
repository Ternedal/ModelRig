package dk.ternedal.modelrig.debug

import android.content.pm.ApplicationInfo
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import dk.ternedal.modelrig.data.TokenStore
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.io.File
import java.security.MessageDigest
import java.time.Instant
import java.util.concurrent.TimeUnit

/**
 * A4-25f pre-grant identity probe.
 *
 * It uses the isolated physical variant's already-paired bearer only to call the
 * normal authenticated `/api/v1/status` endpoint. The bearer is never returned,
 * logged or accepted through adb; only non-secret device/platform/build identity
 * and a hash of the backend URL are persisted in app-private storage.
 */
class Agent4PhysicalDeviceInfoActivity : ComponentActivity() {
    companion object {
        private const val SCHEMA = "modelrig-agent4/a4-25f-device-info/v1"
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE == 0) {
            finishAndRemoveTask()
            return
        }
        Thread {
            val receipt = runCatching(::loadDeviceInfo).fold(
                onSuccess = { it },
                onFailure = { failure ->
                    JSONObject()
                        .put("schema", SCHEMA)
                        .put("recorded_at", Instant.now().toString())
                        .put("stage", "device-info")
                        .put("success", false)
                        .put("failure_type", failure::class.java.simpleName)
                        .put("credential_in_receipt", false)
                        .put("production_activation", false)
                },
            )
            File(filesDir, "a4-25f-device-info.json")
                .writeText(receipt.toString(2) + "\n", Charsets.UTF_8)
            runOnUiThread { finishAndRemoveTask() }
        }.start()
    }

    private fun loadDeviceInfo(): JSONObject {
        val store = TokenStore(this)
        val baseUrl = store.baseUrl?.trim()?.takeIf { it.isNotEmpty() }
            ?: error("paired rig base URL is missing")
        val token = store.token?.takeIf { it.isNotEmpty() }
            ?: error("paired rig credential is missing or invalid")
        val http = OkHttpClient.Builder()
            .connectTimeout(5, TimeUnit.SECONDS)
            .readTimeout(10, TimeUnit.SECONDS)
            .build()
        val request = Request.Builder()
            .url(baseUrl.trimEnd('/') + "/api/v1/status")
            .get()
            .header("Authorization", "Bearer $token")
            .build()
        http.newCall(request).execute().use { response ->
            if (!response.isSuccessful) error("status endpoint rejected physical device")
            val root = JSONObject(response.body?.string().orEmpty())
            val device = root.optJSONObject("device") ?: error("status response missing device")
            val id = device.optString("id").trim()
            val name = device.optString("name").trim()
            require(id.isNotEmpty()) { "status response missing device id" }
            require(name.isNotEmpty()) { "status response missing device name" }
            val packageInfo = packageManager.getPackageInfo(packageName, 0)
            val versionName = packageInfo.versionName?.trim().orEmpty()
            require(versionName.isNotEmpty()) { "A425f package versionName is missing" }
            return JSONObject()
                .put("schema", SCHEMA)
                .put("recorded_at", Instant.now().toString())
                .put("stage", "device-info")
                .put("success", true)
                .put("route_kind", "device-status")
                .put("expected_http_status", 200)
                .put("actual_http_status", response.code)
                .put("device_id", id)
                .put("device_name", name)
                .put("android_manufacturer", Build.MANUFACTURER)
                .put("android_model", Build.MODEL)
                .put("android_version_release", Build.VERSION.RELEASE)
                .put("android_sdk_int", Build.VERSION.SDK_INT)
                .put("app_package_name", packageName)
                .put("app_version_name", versionName)
                .put("app_version_code", packageInfo.longVersionCode)
                .put("app_debuggable", applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE != 0)
                .put("backend_url_sha256", sha256(baseUrl))
                .put("credential_in_receipt", false)
                .put("production_activation", false)
        }
    }

    private fun sha256(value: String): String {
        val digest = MessageDigest.getInstance("SHA-256")
            .digest(value.toByteArray(Charsets.UTF_8))
        return "sha256:" + digest.joinToString("") { "%02x".format(it) }
    }
}
