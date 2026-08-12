package dk.ternedal.modelrig.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.net.ControlCenterScheduleHistory
import dk.ternedal.modelrig.net.ControlCenterScheduleHistoryClient
import dk.ternedal.modelrig.ui.theme.KalivTheme
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * Independent partial-failure boundary for schedule history.
 *
 * The parent Control Center health/capability/grant requests remain usable even
 * when durable history is unavailable or slower than those status reads.
 */
@Composable
internal fun ControlCenterScheduleHistoryLoader(
    baseUrl: String,
    token: String,
    refreshGeneration: Int,
) {
    var history by remember { mutableStateOf<ControlCenterScheduleHistory?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var loading by remember { mutableStateOf(false) }

    LaunchedEffect(baseUrl, token, refreshGeneration) {
        if (baseUrl.isBlank() || token.isBlank()) {
            history = null
            error = "Rig-adgangen mangler. Par appen med ModelRig i Indstillinger først."
            loading = false
            return@LaunchedEffect
        }
        loading = true
        error = null
        val result = withContext(Dispatchers.IO) {
            runCatching { ControlCenterScheduleHistoryClient(baseUrl, token).history() }
        }
        result.onSuccess {
            history = it
            error = null
        }.onFailure {
            history = null
            error = it.message ?: "Execution-historik kunne ikke hentes."
        }
        loading = false
    }

    Column {
        if (loading) {
            Spacer(Modifier.height(6.dp))
            CircularProgressIndicator(
                modifier = Modifier.height(20.dp),
                strokeWidth = 2.dp,
                color = KalivTheme.colors.signal,
            )
            Text(
                "Henter execution-historik…",
                color = KalivTheme.colors.textMuted,
                fontSize = 10.sp,
            )
        }
        ControlCenterScheduleHistorySection(history = history, error = error)
    }
}
