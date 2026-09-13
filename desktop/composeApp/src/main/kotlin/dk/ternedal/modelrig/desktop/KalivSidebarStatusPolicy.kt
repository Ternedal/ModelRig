package dk.ternedal.modelrig.desktop

import java.util.Locale

/** Presentation-only authority for configured desktop chat routing. */
data class KalivSidebarStatus(
    val modelName: String,
    val modelAuthority: String,
    val privacyTitle: String,
    val privacyDetail: String,
    val titleSubtitle: String,
    val localOnly: Boolean,
)

internal fun presentSidebarStatus(
    preferLocal: Boolean,
    autoCloudFallback: Boolean,
    cloudConfigured: Boolean,
    localModel: String,
    cloudModel: String,
): KalivSidebarStatus {
    val localName = localModel.ifBlank { "Lokal model ikke valgt" }
    val cloudName = cloudModel.ifBlank { "Cloud-model ikke valgt" }
    return when {
        !preferLocal && cloudConfigured -> KalivSidebarStatus(
            modelName = cloudName,
            modelAuthority = "Primær · cloud",
            privacyTitle = "Cloud foretrukket",
            privacyDetail = "Chat sendes til cloud først · lokal er fallback",
            titleSubtitle = "— cloud foretrukket",
            localOnly = false,
        )
        !preferLocal -> KalivSidebarStatus(
            modelName = cloudName,
            modelAuthority = "Cloud valgt · ikke konfigureret",
            privacyTitle = "Cloud valgt · ikke klar",
            privacyDetail = "Lokal fallback bruges, hvis den er tilgængelig",
            titleSubtitle = "— cloud valgt · ikke klar",
            localOnly = false,
        )
        autoCloudFallback && cloudConfigured -> KalivSidebarStatus(
            modelName = localName,
            modelAuthority = "Primær · lokal",
            privacyTitle = "Lokal først · cloud muligt",
            privacyDetail = "Fejl før første output kan bruge cloud-fallback",
            titleSubtitle = "— lokal først · cloud muligt",
            localOnly = false,
        )
        autoCloudFallback -> KalivSidebarStatus(
            modelName = localName,
            modelAuthority = "Primær · lokal",
            privacyTitle = "Chat: lokal nu",
            privacyDetail = "Cloud-fallback er slået til, men cloud er ikke konfigureret",
            titleSubtitle = "— lokal AI på din maskine",
            localOnly = true,
        )
        else -> KalivSidebarStatus(
            modelName = localName,
            modelAuthority = "Primær · lokal",
            privacyTitle = "Chat: kun lokal",
            privacyDetail = "Ingen automatisk cloud-fallback",
            titleSubtitle = "— lokal AI på din maskine",
            localOnly = true,
        )
    }
}

internal fun presentLocalModelSelectorLabel(localModel: String): String =
    "Lokal model: ${localModel.ifBlank { "(ikke valgt)" }} ▾"

sealed interface KalivVramTelemetry {
    data object Unavailable : KalivVramTelemetry

    data class Measured(val usedGb: Double, val totalGb: Double) : KalivVramTelemetry {
        init {
            require(usedGb.isFinite() && usedGb >= 0.0) { "usedGb must be finite and non-negative" }
            require(totalGb.isFinite() && totalGb > 0.0) { "totalGb must be finite and positive" }
            require(usedGb <= totalGb) { "usedGb may not exceed totalGb" }
        }
    }
}

internal data class KalivVramPresentation(
    val measured: Boolean,
    val fraction: Float?,
    val label: String,
)

internal fun presentVram(telemetry: KalivVramTelemetry): KalivVramPresentation = when (telemetry) {
    KalivVramTelemetry.Unavailable -> KalivVramPresentation(false, null, "VRAM ikke målt")
    is KalivVramTelemetry.Measured -> KalivVramPresentation(
        measured = true,
        fraction = (telemetry.usedGb / telemetry.totalGb).toFloat(),
        label = "VRAM ${formatGb(telemetry.usedGb)} / ${formatGb(telemetry.totalGb)} GB",
    )
}

private fun formatGb(value: Double): String {
    val formatted = String.format(Locale.US, "%.1f", value)
    return (if (formatted.endsWith(".0")) formatted.dropLast(2) else formatted).replace('.', ',')
}
