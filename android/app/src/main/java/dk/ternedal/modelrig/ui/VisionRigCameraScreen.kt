package dk.ternedal.modelrig.ui

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import dk.ternedal.modelrig.data.TokenStore
import dk.ternedal.modelrig.data.TokenStoreVisionRigSettings
import dk.ternedal.modelrig.data.VisionRigSettings
import dk.ternedal.modelrig.net.VisionRigCameraProducerFactory
import dk.ternedal.modelrig.net.VisionRigConnection
import dk.ternedal.modelrig.net.VisionRigHttp
import dk.ternedal.modelrig.ui.components.kalivScreenInsets
import dk.ternedal.modelrig.ui.theme.KalivTheme
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * The phone camera as VisionRig sensor `kaliv-android` (ModelRig #2275).
 *
 * Approved by Anders 28 Oct 2026, within these limits:
 * - explicit opt-in per device (off by default);
 * - only while this screen is in the foreground: the producer runs inside
 *   repeatOnLifecycle(STARTED) and is closed on ON_STOP;
 * - a visible "Kamera sendes til riggen" banner whenever it runs;
 * - VisionRig's desired-state decides when the camera actually opens.
 * There is no background capture.
 *
 * Developer-only ADB entry (MainActivity EXTRA_VISIONRIG_CAMERA), no navigation.
 */
@Composable
fun VisionRigCameraScreen(
    store: TokenStore,
    producerFactory: VisionRigCameraProducerFactory?,
    onClose: () -> Unit,
) {
    val context = LocalContext.current
    val settings = remember { TokenStoreVisionRigSettings(store) }
    fun granted() = ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) ==
        PackageManager.PERMISSION_GRANTED
    var permission by remember { mutableStateOf(granted()) }
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { permission = it }
    VisionRigCameraContent(
        settings = settings,
        producerFactory = producerFactory,
        cameraPermission = permission,
        requestCameraPermission = { launcher.launch(Manifest.permission.CAMERA) },
        onClose = onClose,
    )
}

@Composable
internal fun VisionRigCameraContent(
    settings: VisionRigSettings,
    producerFactory: VisionRigCameraProducerFactory?,
    cameraPermission: Boolean,
    requestCameraPermission: () -> Unit,
    onClose: () -> Unit,
    io: CoroutineDispatcher = Dispatchers.IO,
) {
    var connection by remember { mutableStateOf(settings.connection()) }
    var optIn by remember { mutableStateOf(settings.cameraOptIn()) }
    var status by remember { mutableStateOf<VisionRigCameraStatus>(VisionRigCameraStatus.Stopped) }
    var notice by remember { mutableStateOf<String?>(null) }
    var attempt by remember { mutableStateOf(0) }
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val paired = connection
    val shouldRun = paired != null && optIn && cameraPermission && producerFactory != null

    LaunchedEffect(shouldRun, paired, attempt) {
        if (!shouldRun || paired == null || producerFactory == null) {
            status = VisionRigCameraStatus.Stopped
            return@LaunchedEffect
        }
        // Foreground only: leaving STARTED cancels this block, which closes the producer.
        lifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
            status = VisionRigCameraStatus.Starting
            val producer = try {
                producerFactory.create(context, lifecycleOwner, paired, VisionRigHttp.client(paired))
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                status = VisionRigCameraPresentation.failure(e)
                return@repeatOnLifecycle
            }
            try {
                withContext(io) {
                    producer.run { step -> status = VisionRigCameraPresentation.afterStep(status, step) }
                }
                status = VisionRigCameraStatus.Stopped
            } catch (e: CancellationException) {
                status = VisionRigCameraStatus.Stopped
                throw e
            } catch (e: Exception) {
                status = VisionRigCameraPresentation.failure(e)
            } finally {
                producer.close()
            }
        }
    }

    Surface(color = KalivTheme.colors.background, modifier = Modifier.fillMaxSize().kalivScreenInsets()) {
        Column(Modifier.fillMaxSize().padding(18.dp).verticalScroll(rememberScrollState())) {
            if (status.producerRunning) {
                Text(
                    "Kamera sendes til riggen",
                    color = KalivTheme.colors.onSignal,
                    modifier = Modifier.fillMaxWidth()
                        .background(KalivTheme.colors.signal)
                        .padding(12.dp)
                        .semantics { liveRegion = LiveRegionMode.Polite },
                )
            }
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp), modifier = Modifier.padding(top = 12.dp)) {
                Button(onClick = onClose) { Text("Tilbage") }
            }
            Text("VisionRig-kamera", color = KalivTheme.colors.textHigh, modifier = Modifier.padding(vertical = 16.dp))
            notice?.let { Text(it, color = KalivTheme.colors.danger, modifier = Modifier.padding(bottom = 12.dp)) }
            if (paired == null) {
                PairingForm(
                    unreadable = settings.credentialUnreadable(),
                    onSave = { candidate ->
                        if (settings.save(candidate)) {
                            connection = candidate
                            notice = null
                        } else {
                            notice = "VisionRig-parringen kunne ikke gemmes sikkert."
                        }
                    },
                )
                return@Column
            }
            Text("Parret med ${paired.origin.host}:${paired.origin.port}", color = KalivTheme.colors.textMuted)
            Text(
                "Når det er slået til, sendes kameraet kun mens denne skærm er åben. " +
                    "VisionRig bestemmer, hvornår kameraet faktisk tændes.",
                color = KalivTheme.colors.textMuted,
                modifier = Modifier.padding(vertical = 12.dp),
            )
            when {
                producerFactory == null -> Text(
                    "VisionRig-producenten er ikke bygget ind i denne version endnu.",
                    color = KalivTheme.colors.textMuted,
                )
                !optIn -> Button(onClick = {
                    if (settings.setCameraOptIn(true)) {
                        optIn = true
                        notice = null
                        if (!cameraPermission) requestCameraPermission()
                    } else {
                        notice = "Valget kunne ikke gemmes."
                    }
                }) { Text("Send kameraet til VisionRig") }
                else -> {
                    if (!cameraPermission) {
                        Text("Kamera-tilladelse mangler.", color = KalivTheme.colors.danger)
                        Button(onClick = requestCameraPermission) { Text("Giv tilladelse") }
                    }
                    Text(
                        VisionRigCameraPresentation.statusText(status),
                        color = if (status is VisionRigCameraStatus.Failed) KalivTheme.colors.danger else KalivTheme.colors.textHigh,
                        modifier = Modifier.padding(vertical = 8.dp),
                    )
                    if (status is VisionRigCameraStatus.Failed) {
                        Button(onClick = { attempt++ }) { Text("Prøv igen") }
                    }
                    Button(onClick = {
                        if (settings.setCameraOptIn(false)) optIn = false else notice = "Valget kunne ikke gemmes."
                    }) { Text("Stop kameraet") }
                }
            }
            Button(
                onClick = {
                    if (settings.clear()) {
                        optIn = false
                        connection = null
                        notice = null
                    } else {
                        notice = "VisionRig-parringen kunne ikke fjernes."
                    }
                },
                modifier = Modifier.padding(top = 24.dp),
            ) { Text("Glem VisionRig-parring") }
        }
    }
}

@Composable
private fun PairingForm(unreadable: Boolean, onSave: (VisionRigConnection) -> Unit) {
    var url by remember { mutableStateOf("") }
    var token by remember { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }
    if (unreadable) {
        Text(
            "Det gemte VisionRig-token kan ikke længere læses. Par igen.",
            color = KalivTheme.colors.danger,
            modifier = Modifier.padding(bottom = 12.dp),
        )
    }
    OutlinedTextField(
        value = url,
        onValueChange = { url = it },
        label = { Text("VisionRig-gateway") },
        placeholder = { Text("http://192.168.1.10:8111") },
        singleLine = true,
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
        modifier = Modifier.fillMaxWidth(),
    )
    OutlinedTextField(
        value = token,
        onValueChange = { token = it },
        label = { Text("Producer-token") },
        singleLine = true,
        visualTransformation = PasswordVisualTransformation(),
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
        modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
    )
    error?.let { Text(it, color = KalivTheme.colors.danger, modifier = Modifier.padding(top = 8.dp)) }
    Button(
        onClick = {
            VisionRigConnection.create(url, token).fold(
                onSuccess = {
                    error = null
                    token = ""
                    onSave(it)
                },
                onFailure = { error = it.message ?: "Ugyldig parring" },
            )
        },
        modifier = Modifier.padding(top = 12.dp),
    ) { Text("Gem parring") }
}
