package dk.ternedal.modelrig.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.FilterChip
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
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
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import dk.ternedal.modelrig.data.TokenStore
import dk.ternedal.modelrig.net.MediaJobClient
import dk.ternedal.modelrig.net.MediaJobException
import dk.ternedal.modelrig.net.MediaJobSource
import dk.ternedal.modelrig.ui.components.kalivScreenInsets
import dk.ternedal.modelrig.ui.theme.KalivTheme
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * Create one image on the paired rig (#2275 A1): profile, size, prompt,
 * "Generér", live status, cancel, and "Åbn galleriet" once it is done.
 *
 * Reached only through MainActivity's EXTRA_MEDIA_GENERATE, like the gallery:
 * the job API is default-off on the rig and not on main yet. Without it the
 * screen says generation is not available and offers nothing else.
 *
 * The prompt is held in Compose memory only (`remember`, not
 * `rememberSaveable`): it is not written to the saved instance state, a log or
 * storage, and it is gone when the screen closes.
 */
@Composable
fun MediaGenerateScreen(store: TokenStore, onOpenGallery: () -> Unit, onClose: () -> Unit) {
    val baseUrl = store.baseUrl
    val token = store.token
    val source = remember(baseUrl, token) { runCatching { MediaJobClient(baseUrl, token) } }
    source.fold(
        onSuccess = { MediaGenerateContent(it, onOpenGallery, onClose) },
        onFailure = { error ->
            val message = (error as? MediaJobException)?.let(MediaGenerate::message) ?: "Billedgenerering er ikke tilgængelig"
            GenerateSurface {
                Button(onClick = onClose) { Text("Tilbage") }
                Title()
                Text(message, color = KalivTheme.colors.danger, modifier = Modifier.testTag("generate-unavailable"))
            }
        },
    )
}

@Composable
internal fun MediaGenerateContent(
    source: MediaJobSource,
    onOpenGallery: () -> Unit,
    onClose: () -> Unit,
    io: CoroutineDispatcher = Dispatchers.IO,
    pollMillis: Long = MediaGenerate.POLL_MILLIS,
) {
    var state by remember { mutableStateOf(MediaGenerateState()) }
    val scope = rememberCoroutineScope()

    fun failure(error: Throwable): MediaJobException = error as? MediaJobException
        ?: MediaJobException(MediaJobException.Reason.UNAVAILABLE, "Uventet svar fra riggen")

    LaunchedEffect(Unit) {
        val result = withContext(io) { runCatching { source.profiles() } }
        state = result.fold(
            onSuccess = { MediaGenerate.profilesLoaded(state, it) },
            onFailure = { MediaGenerate.profilesFailed(state, failure(it)) },
        )
    }

    // Poll while a job is followed; the effect is cancelled when the job finishes or the
    // screen leaves the composition, so nothing keeps asking the rig in the background.
    val followedId = (state.phase as? MediaGeneratePhase.Following)?.job?.id
    LaunchedEffect(followedId) {
        val id = followedId ?: return@LaunchedEffect
        while (true) {
            delay(MediaGenerate.pollDelay(state, pollMillis))  // backs off while the rig is not answering
            val result = withContext(io) { runCatching { source.status(id) } }
            state = result.fold(
                onSuccess = { MediaGenerate.polled(state, it) },
                onFailure = { MediaGenerate.pollFailed(state, failure(it)) },
            )
            if (!state.polling) break
        }
    }

    fun submit() {
        val request = MediaGenerate.request(state) ?: return
        val profile = state.profile ?: return
        state = MediaGenerate.submitting(state)
        scope.launch {
            val result = withContext(io) { runCatching { source.submit(request, profile) } }
            state = result.fold(
                onSuccess = { MediaGenerate.submitted(state, it) },
                onFailure = { MediaGenerate.submitFailed(state, failure(it)) },
            )
        }
    }

    fun cancel() {
        val id = (state.phase as? MediaGeneratePhase.Following)?.job?.id ?: return
        if (!state.canCancel) return
        state = MediaGenerate.cancelling(state)
        scope.launch {
            val result = withContext(io) { runCatching { source.cancel(id) } }
            state = result.fold(
                onSuccess = { MediaGenerate.cancelled(state, it) },
                onFailure = { MediaGenerate.cancelFailed(state, failure(it)) },
            )
        }
    }

    GenerateSurface {
        Button(onClick = onClose) { Text("Tilbage") }
        Title()
        when (val phase = state.phase) {
            MediaGeneratePhase.Loading -> Text("Spørger riggen …", color = KalivTheme.colors.textMuted,
                modifier = Modifier.testTag("generate-loading"))
            is MediaGeneratePhase.Unavailable -> Text(phase.message, color = KalivTheme.colors.danger,
                modifier = Modifier.testTag("generate-unavailable"))
            else -> Form(state, onState = { state = it }, onSubmit = ::submit, onCancel = ::cancel,
                onOpenGallery = onOpenGallery, onResume = { state = MediaGenerate.resume(state) })
        }
    }
}

@Composable
private fun Form(
    state: MediaGenerateState,
    onState: (MediaGenerateState) -> Unit,
    onSubmit: () -> Unit,
    onCancel: () -> Unit,
    onOpenGallery: () -> Unit,
    onResume: () -> Unit,
) {
    val editable = state.phase == MediaGeneratePhase.Ready || state.phase is MediaGeneratePhase.Finished
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        if (state.profiles.size > 1) {
            Text("Profil", color = KalivTheme.colors.textMuted)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                state.profiles.forEach { p ->
                    FilterChip(selected = p.profileId == state.profileId, enabled = editable,
                        onClick = { onState(MediaGenerate.selectProfile(state, p.profileId)) },
                        label = { Text(p.profileId) })
                }
            }
        }
        state.profile?.let { p ->
            Text("Størrelse", color = KalivTheme.colors.textMuted)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                p.sizes.forEach { size ->
                    FilterChip(selected = size == state.size, enabled = editable,
                        onClick = { onState(MediaGenerate.selectSize(state, size)) },
                        label = { Text("${size.first}×${size.second}") })
                }
            }
            OutlinedTextField(
                value = state.prompt,
                onValueChange = { onState(MediaGenerate.editPrompt(state, it)) },
                enabled = editable,
                label = { Text("Beskriv billedet") },
                supportingText = { Text("${state.prompt.length}/${p.maxPromptChars}") },
                minLines = 3,
                modifier = Modifier.fillMaxWidth().testTag("generate-prompt"),
            )
        }
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Button(onClick = onSubmit, enabled = state.canSubmit, modifier = Modifier.testTag("generate-submit")) {
                Text(if (state.phase == MediaGeneratePhase.Submitting) "Sender …" else "Generér")
            }
            if (state.phase is MediaGeneratePhase.Following) {
                OutlinedButton(onClick = onCancel, enabled = state.canCancel, modifier = Modifier.testTag("generate-cancel")) {
                    Text("Annullér")
                }
            }
        }
        when (val phase = state.phase) {
            is MediaGeneratePhase.Following -> Text(
                if (phase.cancelling) "Annulleres …" else MediaGenerate.stateLabel(phase.job),
                color = KalivTheme.colors.textHigh, modifier = Modifier.testTag("generate-status"),
            )
            is MediaGeneratePhase.Stalled -> {
                Text(MediaGenerate.stateLabel(phase.job), color = KalivTheme.colors.textMuted,
                    modifier = Modifier.testTag("generate-status"))
                Button(onClick = onResume, modifier = Modifier.testTag("generate-resume")) { Text("Prøv igen") }
            }
            is MediaGeneratePhase.Finished -> {
                Text(MediaGenerate.stateLabel(phase.job),
                    color = if (state.completedAssetId != null) KalivTheme.colors.textHigh else KalivTheme.colors.danger,
                    modifier = Modifier.testTag("generate-status"))
                if (state.completedAssetId != null) {
                    Button(onClick = onOpenGallery, modifier = Modifier.testTag("generate-open-gallery")) {
                        Text("Åbn galleriet")
                    }
                }
            }
            else -> Unit
        }
        state.error?.let {
            Text(it, color = KalivTheme.colors.danger, modifier = Modifier.testTag("generate-error"))
        }
    }
}

@Composable
private fun Title() {
    Text("Generér billede", color = KalivTheme.colors.textHigh, modifier = Modifier.padding(vertical = 16.dp))
}

@Composable
private fun GenerateSurface(content: @Composable () -> Unit) {
    Surface(color = KalivTheme.colors.background, modifier = Modifier.fillMaxSize().kalivScreenInsets()) {
        Column(Modifier.fillMaxSize().padding(18.dp).verticalScroll(rememberScrollState())) { content() }
    }
}
