package dk.ternedal.modelrig.desktop

import java.util.Locale

/**
 * Truthful authority for the desktop performance card.
 *
 * Product UI must distinguish absent measurement from a real observation; it
 * must never substitute reference/demo telemetry for a response that was not
 * measured.
 */
sealed interface KalivPerformanceTelemetry {
    data object Unavailable : KalivPerformanceTelemetry

    data class Measured(
        val tokensPerSecond: Int,
        val responseSeconds: Double,
        val sparkline: List<Float> = emptyList(),
    ) : KalivPerformanceTelemetry {
        init {
            require(tokensPerSecond >= 0) { "tokensPerSecond must be non-negative" }
            require(responseSeconds.isFinite() && responseSeconds >= 0.0) {
                "responseSeconds must be finite and non-negative"
            }
            require(sparkline.all(Float::isFinite)) { "sparkline values must be finite" }
        }
    }
}

internal data class KalivPerformancePresentation(
    val measured: Boolean,
    val tokensPerSecondText: String,
    val responseTimeText: String,
    val sparkline: List<Float>?,
)

internal fun presentPerformance(
    telemetry: KalivPerformanceTelemetry,
): KalivPerformancePresentation = when (telemetry) {
    KalivPerformanceTelemetry.Unavailable -> KalivPerformancePresentation(
        measured = false,
        tokensPerSecondText = "Ikke målt endnu",
        responseTimeText = "—",
        sparkline = null,
    )

    is KalivPerformanceTelemetry.Measured -> KalivPerformancePresentation(
        measured = true,
        tokensPerSecondText = telemetry.tokensPerSecond.toString(),
        responseTimeText = String.format(Locale.US, "%.2f", telemetry.responseSeconds)
            .replace('.', ',') + " s",
        sparkline = telemetry.sparkline.takeIf { it.size >= 2 },
    )
}
