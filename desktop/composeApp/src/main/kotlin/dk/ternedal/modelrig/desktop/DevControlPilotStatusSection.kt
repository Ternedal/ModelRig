package dk.ternedal.modelrig.desktop

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.desktop.net.DevControlPilotStatus
import dk.ternedal.modelrig.desktop.net.DevControlPilotStatusClient
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

internal fun desktopDevControlStatusError(raw: String?): String {
    val message = raw.orEmpty()
    return when {
        message.contains("(401)") ->
            "Ikke godkendt. Parringen mangler eller er udløbet."
        message.contains("timed out", ignoreCase = true) ||
            message.contains("HttpTimeout", ignoreCase = true) ->
            "DevControl-status fik tidsudløb. Prøv igen."
        message.contains("Connection refused", ignoreCase = true) ||
            message.contains("ConnectException") ->
            "Kan ikke nå riggen for DevControl-status."
        else -> "DevControl-status kunne ikke hentes sikkert."
    }
}

/**
 * Observation-only DC-L16 projection inside Desktop Control Center.
 *
 * The section has no controls of its own. It refreshes only when the dialog is
 * opened or the existing operator-driven Control Center refresh generation
 * changes. A backend 404 means the exact-default-off feature is absent and the
 * section remains invisible.
 */
@Composable
internal fun DevControlPilotStatusSection(
    baseUrl: String,
    token: String,
    refreshGeneration: Int,
) {
    var status by remember { mutableStateOf<DevControlPilotStatus?>(null) }
    var error by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(baseUrl, token, refreshGeneration) {
        status = null
        error = null
        if (baseUrl.isBlank() || token.isBlank()) return@LaunchedEffect

        val result = withContext(Dispatchers.IO) {
            runCatching { DevControlPilotStatusClient(baseUrl, token).status() }
        }
        result.onSuccess {
            status = it
            error = null
        }.onFailure {
            status = null
            error = desktopDevControlStatusError(it.message)
        }
    }

    val current = status
    val currentError = error
    if (current == null && currentError == null) return

    Column(
        modifier = Modifier.padding(top = 8.dp, bottom = 2.dp),
        verticalArrangement = Arrangement.spacedBy(2.dp),
    ) {
        Text(
            "DevControl pilot",
            color = KalivTheme.colors.TextHigh,
            fontSize = 18.sp,
            fontWeight = FontWeight.SemiBold,
        )
        Text(
            "DC-L16 · kun observation · manuel refresh",
            color = KalivTheme.colors.TextMuted,
            fontSize = 10.sp,
        )
    }

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .background(KalivTheme.colors.Surface, RoundedCornerShape(12.dp))
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        if (currentError != null) {
            Text(
                "Status kunne ikke verificeres",
                color = KalivTheme.colors.TextHigh,
                fontWeight = FontWeight.SemiBold,
            )
            Text(currentError, color = KalivTheme.colors.TextMuted, fontSize = 11.sp)
            Text(
                "Ingen pilot- eller execution-authority antages ved fejl.",
                color = KalivTheme.colors.TextMuted,
                fontSize = 10.sp,
            )
            return@Column
        }

        requireNotNull(current)
        Text(
            "Produktfladen er aktiveret · piloten er ikke startet",
            color = KalivTheme.colors.TextHigh,
            fontWeight = FontWeight.SemiBold,
        )
        Text(
            "Feature flag: ${current.featureFlag}",
            color = KalivTheme.colors.TextMuted,
            fontSize = 10.sp,
        )
        Text(
            "Task registry: ikke klar · runtime preflight: ikke opfyldt",
            color = KalivTheme.colors.TextMuted,
            fontSize = 11.sp,
        )
        Text(
            "Pilotstart og lokale commits: ikke autoriseret",
            color = KalivTheme.colors.TextMuted,
            fontSize = 11.sp,
        )
        Text(
            "Remote transport, writes, push, PR, merge, release og deploy: ikke autoriseret",
            color = KalivTheme.colors.TextMuted,
            fontSize = 11.sp,
        )
        Text(
            "Production activation: ikke autoriseret",
            color = KalivTheme.colors.TextMuted,
            fontSize = 11.sp,
        )
        Text(
            "Ingen Start-knap · ingen automatisk polling",
            color = KalivTheme.colors.TextMuted,
            fontSize = 10.sp,
        )
    }
}
