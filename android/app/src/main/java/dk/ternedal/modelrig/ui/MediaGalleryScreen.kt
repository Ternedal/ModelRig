package dk.ternedal.modelrig.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import dk.ternedal.modelrig.data.TokenStore
import dk.ternedal.modelrig.net.MediaGalleryClient
import dk.ternedal.modelrig.net.MediaGalleryEntry
import dk.ternedal.modelrig.ui.theme.KalivTheme
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * Experimental, read-only gallery surface. Not yet wired into app navigation.
 * Media selection is a callback so playback can be supplied by the host app.
 */
@Composable
fun MediaGalleryScreen(
    store: TokenStore,
    onClose: () -> Unit,
    onOpen: (MediaGalleryEntry) -> Unit
) {
    var items by remember { mutableStateOf<List<MediaGalleryEntry>>(emptyList()) }
    var error by remember { mutableStateOf<String?>(null) }
    var loading by remember { mutableStateOf(false) }
    var selected by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()

    suspend fun refresh() {
        loading = true
        val result = withContext(Dispatchers.IO) {
            runCatching {
                MediaGalleryClient(store.baseUrl.orEmpty(), store.token.orEmpty()).list()
            }
        }
        result.onSuccess { items = it; error = null }
            .onFailure { error = it.message ?: "Mediebiblioteket kunne ikke hentes" }
        loading = false
    }

    LaunchedEffect(Unit) { refresh() }
    Surface(color = KalivTheme.colors.background, modifier = Modifier.fillMaxSize()) {
        Column(Modifier.fillMaxSize().padding(18.dp).verticalScroll(rememberScrollState())) {
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Button(onClick = onClose) { Text("Tilbage") }
                Button(onClick = { scope.launch { refresh() } }, enabled = !loading) {
                    Text(if (loading) "Henter…" else "Opdater")
                }
            }
            Text("Mediebibliotek", color = KalivTheme.colors.textHigh,
                modifier = Modifier.padding(vertical = 16.dp))
            error?.let { Text(it, color = KalivTheme.colors.danger) }
            if (!loading && error == null && items.isEmpty()) {
                Text("Ingen billeder eller videoer endnu.", color = KalivTheme.colors.textMuted)
            }
            selected?.let { id ->
                Text("Valgt medie: " + id + " · afspilning endnu ikke tilgængelig",
                    color = KalivTheme.colors.textMuted)
            }
            items.forEach { entry ->
                Row(
                    modifier = Modifier.fillMaxWidth()
                        .clickable { selected = entry.id; onOpen(entry) }
                        .padding(vertical = 14.dp),
                    horizontalArrangement = Arrangement.SpaceBetween
                ) {
                    Text(entry.id, color = KalivTheme.colors.textHigh)
                    Text(entry.kind + " · " + entry.projection,
                        color = KalivTheme.colors.textMuted)
                }
            }
        }
    }
}
