package dk.ternedal.modelrig.ui

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.LocalLifecycleOwner
import dk.ternedal.modelrig.R
import dk.ternedal.modelrig.net.PairingLink
import dk.ternedal.modelrig.net.QrDecoder
import dk.ternedal.modelrig.ui.chat.ConversationsTopBar
import dk.ternedal.modelrig.ui.components.kalivScreenInsets
import dk.ternedal.modelrig.ui.theme.KalivTheme
import dk.ternedal.modelrig.ui.theme.KalivTokens
import dk.ternedal.modelrig.ui.theme.KalivType
import java.util.concurrent.Executors

/**
 * QR-skanner til parring.
 *
 * Skærmen LEVERER et parringslink — den parrer ikke. Et fund lukker
 * skanneren og lander i parringskortets bekræftelse, hvor værten står
 * skrevet ud og et tryk stadig mangler. Se PairingLink for hvorfor.
 *
 * Kameraet ejes af CameraX og bindes til skærmens livscyklus; billederne
 * afkodes af QrDecoder, som ikke rører Android og derfor er enhedstestet.
 * Frames der ikke indeholder en kode er normaltilstanden — de kastes væk
 * uden støj, og først et link der PARSER som vores form afslutter skanningen.
 */
@Composable
fun QrScanScreen(onBack: () -> Unit, onLink: (PairingLink) -> Unit) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val latestOnLink by rememberUpdatedState(onLink)

    var hasPermission by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) ==
                PackageManager.PERMISSION_GRANTED,
        )
    }
    var error by remember { mutableStateOf<String?>(null) }
    var handled by remember { mutableStateOf(false) }

    val ask = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        hasPermission = granted
        if (!granted) error = "Kameraet er ikke tilladt. Du kan stadig indtaste koden i hånden."
    }
    LaunchedEffect(Unit) { if (!hasPermission) ask.launch(Manifest.permission.CAMERA) }

    val executor = remember { Executors.newSingleThreadExecutor() }
    DisposableEffect(Unit) { onDispose { executor.shutdown() } }

    Column(
        Modifier
            .fillMaxSize()
            .background(KalivTheme.colors.background)
            .kalivScreenInsets(),
    ) {
        ConversationsTopBar(title = "Skan QR", onBack = onBack)
        Box(
            Modifier
                .fillMaxWidth()
                .weight(1f)
                .padding(horizontal = 15.dp)
                .background(KalivTheme.colors.surfaceDim, RoundedCornerShape(KalivTokens.Radius.card))
                .border(
                    KalivTokens.Layout.hairline,
                    KalivTheme.colors.hairline,
                    RoundedCornerShape(KalivTokens.Radius.card),
                ),
            contentAlignment = Alignment.Center,
        ) {
            if (hasPermission) {
                AndroidView(
                    modifier = Modifier.fillMaxSize().padding(1.dp),
                    factory = { ctx ->
                        val view = PreviewView(ctx)
                        val providerFuture = ProcessCameraProvider.getInstance(ctx)
                        providerFuture.addListener({
                            val provider = runCatching { providerFuture.get() }.getOrNull()
                            if (provider == null) {
                                error = "Kameraet kunne ikke startes."
                                return@addListener
                            }
                            val preview = Preview.Builder().build()
                                .also { it.surfaceProvider = view.surfaceProvider }
                            val analysis = ImageAnalysis.Builder()
                                .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                                .build()
                            analysis.setAnalyzer(executor) { image -> scan(image, handled) { link ->
                                if (!handled) {
                                    handled = true
                                    latestOnLink(link)
                                }
                            } }
                            runCatching {
                                provider.unbindAll()
                                provider.bindToLifecycle(
                                    lifecycleOwner, CameraSelector.DEFAULT_BACK_CAMERA, preview, analysis,
                                )
                            }.onFailure { error = "Kameraet kunne ikke startes." }
                        }, ContextCompat.getMainExecutor(ctx))
                        view
                    },
                )
            } else {
                Column(
                    Modifier.padding(24.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    androidx.compose.material3.Icon(
                        androidx.compose.ui.res.painterResource(R.drawable.ic_kaliv_shield),
                        contentDescription = null,
                        tint = KalivTheme.colors.textMuted,
                        modifier = Modifier.size(22.dp),
                    )
                    Spacer(Modifier.height(9.dp))
                    androidx.compose.material3.Text(
                        "Kameraet bruges kun her, og kun til at læse parringskoden.",
                        style = TextStyle(fontFamily = KalivType.Inter, fontSize = 14.5.sp),
                        color = KalivTheme.colors.textMuted,
                    )
                }
            }
        }
        Spacer(Modifier.height(11.dp))
        androidx.compose.material3.Text(
            error ?: "Hold koden fra riggen i billedet. Intet parres af sig selv — du får adressen at se først.",
            style = TextStyle(
                fontFamily = KalivType.Inter,
                fontWeight = if (error != null) FontWeight.Medium else FontWeight.Normal,
                fontSize = 13.5.sp,
            ),
            color = if (error != null) KalivTheme.colors.danger else KalivTheme.colors.textMuted,
            modifier = Modifier.padding(horizontal = 15.dp, vertical = 4.dp),
        )
        Spacer(Modifier.height(14.dp))
    }
}

/**
 * Én frame: tag Y-planet, afkod, og lever KUN videre hvis teksten parser
 * som et parringslink. En fremmed QR (en billet, et wifi-netværk) er ikke
 * en fejl — den ignoreres, og skanneren kører videre.
 */
private inline fun scan(image: ImageProxy, alreadyHandled: Boolean, onFound: (PairingLink) -> Unit) {
    try {
        if (alreadyHandled) return
        val plane = image.planes.firstOrNull() ?: return
        val buffer = plane.buffer
        val bytes = ByteArray(buffer.remaining())
        buffer.get(bytes)
        val text = QrDecoder.decodeLuminance(bytes, image.width, image.height) ?: return
        PairingLink.parse(text)?.let(onFound)
    } finally {
        image.close()
    }
}
