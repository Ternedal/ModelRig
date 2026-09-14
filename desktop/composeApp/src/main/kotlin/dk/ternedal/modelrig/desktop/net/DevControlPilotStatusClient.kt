package dk.ternedal.modelrig.desktop.net

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import java.net.URI
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.time.Duration

@Serializable
private data class DevControlPilotStatusWire(
    val schema: String,
    @SerialName("feature_flag") val featureFlag: String,
    val enabled: Boolean,
    @SerialName("operator_surface") val operatorSurface: String,
    @SerialName("route_scope") val routeScope: String,
    @SerialName("manual_refresh_only") val manualRefreshOnly: Boolean,
    @SerialName("automatic_polling") val automaticPolling: Boolean,
    @SerialName("unattended_cadence") val unattendedCadence: Boolean,
    @SerialName("task_registry_ready") val taskRegistryReady: Boolean,
    @SerialName("runtime_preflight_satisfied") val runtimePreflightSatisfied: Boolean,
    @SerialName("pilot_start_authorized") val pilotStartAuthorized: Boolean,
    @SerialName("product_pilot_started") val productPilotStarted: Boolean,
    @SerialName("local_commit_authorized") val localCommitAuthorized: Boolean,
    @SerialName("remote_transport_available") val remoteTransportAvailable: Boolean,
    @SerialName("remote_write_authorized") val remoteWriteAuthorized: Boolean,
    @SerialName("push_authorized") val pushAuthorized: Boolean,
    @SerialName("pr_mutation_authorized") val prMutationAuthorized: Boolean,
    @SerialName("merge_authorized") val mergeAuthorized: Boolean,
    @SerialName("release_authorized") val releaseAuthorized: Boolean,
    @SerialName("deploy_authorized") val deployAuthorized: Boolean,
    @SerialName("production_activation_authorized") val productionActivationAuthorized: Boolean,
    val authority: String,
)

/**
 * Read-only desktop projection of the DC-L16 product status seam.
 *
 * A 404 is the normal default-off state and is returned as null. Any mounted
 * route must remain the exact observation-only contract; broadened execution,
 * publication or activation authority is rejected before the UI can render it.
 */
class DevControlPilotStatusClient(baseUrl: String, private val bearer: String) {
    companion object {
        const val SCHEMA = "kaliv-devcontrol-pilot-status/v1"
        const val FEATURE_FLAG = "KALIV_DEVCONTROL_PILOT"
        const val ROUTE = "/api/v1/experimental/devcontrol-pilot/status"
        const val AUTHORITY = "dc-l16-product-status-observation-only"
    }

    private val base = baseUrl.trimEnd('/')
    private val json = Json { ignoreUnknownKeys = false; explicitNulls = false }
    private val http = HttpClient.newBuilder()
        .connectTimeout(Duration.ofSeconds(5))
        .build()

    fun status(): DevControlPilotStatus? {
        val request = HttpRequest.newBuilder(URI.create(base + ROUTE))
            .header("Accept", "application/json")
            .header("Authorization", "Bearer $bearer")
            .timeout(Duration.ofSeconds(10))
            .GET()
            .build()
        val response = try {
            http.send(request, HttpResponse.BodyHandlers.ofString())
        } catch (exc: Exception) {
            throw ControlCenterException(
                "DevControl pilot status failed: ${exc::class.simpleName}",
            )
        }
        if (response.statusCode() == 404) return null
        if (response.statusCode() !in 200..299) {
            throw ControlCenterException(
                "DevControl pilot status failed (${response.statusCode()}): " +
                    response.body().take(500),
            )
        }
        return parse(response.body())
    }

    internal fun parse(body: String): DevControlPilotStatus {
        val wire = try {
            json.decodeFromString<DevControlPilotStatusWire>(body)
        } catch (exc: Exception) {
            fail("invalid JSON: ${exc::class.simpleName}")
        }
        if (wire.schema != SCHEMA) fail("unsupported schema ${wire.schema}")
        if (wire.featureFlag != FEATURE_FLAG) fail("unexpected feature flag")
        if (!wire.enabled) fail("mounted route must report enabled=true")
        if (wire.operatorSurface != "desktop.control-center") fail("unexpected operator surface")
        if (wire.routeScope != "read-only-status-only") fail("unexpected route scope")
        if (!wire.manualRefreshOnly) fail("manual refresh invariant missing")
        if (wire.authority != AUTHORITY) fail("unexpected authority")

        val forbidden = linkedMapOf(
            "automatic_polling" to wire.automaticPolling,
            "unattended_cadence" to wire.unattendedCadence,
            "task_registry_ready" to wire.taskRegistryReady,
            "runtime_preflight_satisfied" to wire.runtimePreflightSatisfied,
            "pilot_start_authorized" to wire.pilotStartAuthorized,
            "product_pilot_started" to wire.productPilotStarted,
            "local_commit_authorized" to wire.localCommitAuthorized,
            "remote_transport_available" to wire.remoteTransportAvailable,
            "remote_write_authorized" to wire.remoteWriteAuthorized,
            "push_authorized" to wire.pushAuthorized,
            "pr_mutation_authorized" to wire.prMutationAuthorized,
            "merge_authorized" to wire.mergeAuthorized,
            "release_authorized" to wire.releaseAuthorized,
            "deploy_authorized" to wire.deployAuthorized,
            "production_activation_authorized" to wire.productionActivationAuthorized,
        )
        forbidden.entries.firstOrNull { it.value }?.let {
            fail("${it.key} must remain false")
        }

        return DevControlPilotStatus(
            featureFlag = wire.featureFlag,
            enabled = wire.enabled,
            operatorSurface = wire.operatorSurface,
            routeScope = wire.routeScope,
            manualRefreshOnly = wire.manualRefreshOnly,
            taskRegistryReady = wire.taskRegistryReady,
            runtimePreflightSatisfied = wire.runtimePreflightSatisfied,
            pilotStartAuthorized = wire.pilotStartAuthorized,
            productPilotStarted = wire.productPilotStarted,
            localCommitAuthorized = wire.localCommitAuthorized,
            remoteTransportAvailable = wire.remoteTransportAvailable,
            remoteWriteAuthorized = wire.remoteWriteAuthorized,
            pushAuthorized = wire.pushAuthorized,
            prMutationAuthorized = wire.prMutationAuthorized,
            mergeAuthorized = wire.mergeAuthorized,
            releaseAuthorized = wire.releaseAuthorized,
            deployAuthorized = wire.deployAuthorized,
            productionActivationAuthorized = wire.productionActivationAuthorized,
            authority = wire.authority,
        )
    }

    private fun fail(message: String): Nothing =
        throw ControlCenterException("Invalid DevControl pilot status: $message")
}

data class DevControlPilotStatus(
    val featureFlag: String,
    val enabled: Boolean,
    val operatorSurface: String,
    val routeScope: String,
    val manualRefreshOnly: Boolean,
    val taskRegistryReady: Boolean,
    val runtimePreflightSatisfied: Boolean,
    val pilotStartAuthorized: Boolean,
    val productPilotStarted: Boolean,
    val localCommitAuthorized: Boolean,
    val remoteTransportAvailable: Boolean,
    val remoteWriteAuthorized: Boolean,
    val pushAuthorized: Boolean,
    val prMutationAuthorized: Boolean,
    val mergeAuthorized: Boolean,
    val releaseAuthorized: Boolean,
    val deployAuthorized: Boolean,
    val productionActivationAuthorized: Boolean,
    val authority: String,
)
