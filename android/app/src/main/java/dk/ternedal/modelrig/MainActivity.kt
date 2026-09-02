package dk.ternedal.modelrig

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.runtime.remember
import androidx.core.splashscreen.SplashScreen.Companion.installSplashScreen
import dk.ternedal.modelrig.data.TokenStore
import dk.ternedal.modelrig.ui.Agent3CapabilityScreen
import dk.ternedal.modelrig.ui.Agent3MemoryScreen
import dk.ternedal.modelrig.ui.Agent3ReplanScreen
import dk.ternedal.modelrig.ui.Agent3ReviewScreen
import dk.ternedal.modelrig.ui.Agent3Screen
import dk.ternedal.modelrig.ui.Agent3TaskScreen
import dk.ternedal.modelrig.ui.PersonsScreen
import dk.ternedal.modelrig.ui.Agent3ValidationScreen
import dk.ternedal.modelrig.ui.AppEntryUi
import dk.ternedal.modelrig.ui.ScheduleScreen
import dk.ternedal.modelrig.ui.theme.ModelRigTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        // Must run before super.onCreate: this is what turns the launch into a
        // real Android 12+ splash (ankh on the mode's background) instead of a
        // window-background flash the system splash would paint over.
        installSplashScreen()
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()

        // Explicit control-surface entries. The normal launcher sends none of
        // these extras, so ordinary launch still gets AppUi through AppEntryUi.
        // Scheduler and the readiness-routed read-only task surface are
        // human-facing app shortcuts; the remaining Agent 3 entries stay
        // developer-only ADB surfaces.
        val openSchedules =
            intent?.getBooleanExtra(EXTRA_SCHEDULES, false) == true ||
                (intent?.data?.scheme == "kaliv" && intent?.data?.host == "schedules")
        val openAgent3Task =
            intent?.getBooleanExtra(EXTRA_AGENT3_TASK, false) == true ||
                (intent?.data?.scheme == "kaliv" && intent?.data?.host == "tasks")
        val openPersons =
            intent?.getBooleanExtra(EXTRA_PERSONS, false) == true ||
                (intent?.data?.scheme == "kaliv" && intent?.data?.host == "persons")
        val openAgent3 = intent?.getBooleanExtra(EXTRA_AGENT3, false) == true
        val openAgent3Memory = intent?.getBooleanExtra(EXTRA_AGENT3_MEMORY, false) == true
        val openAgent3Validation = intent?.getBooleanExtra(EXTRA_AGENT3_VALIDATION, false) == true
        val openAgent3Capabilities = intent?.getBooleanExtra(EXTRA_AGENT3_CAPABILITIES, false) == true
        val openAgent3Replan = intent?.getBooleanExtra(EXTRA_AGENT3_REPLAN, false) == true
        val openAgent3Review = intent?.getBooleanExtra(EXTRA_AGENT3_REVIEW, false) == true
        // kaliv://pair?url=...&code=... — parseren er fail-closed; et ugyldigt
        // link giver null og dermed helt almindelig opstart.
        val pairingLink = dk.ternedal.modelrig.net.PairingLink.parse(intent?.data?.toString())
        // Del til Kaliv: en anden app har sendt tekst eller en fil hertil. Vi
        // laeser KUN hvad der blev delt; hvad der skal ske med det, bestemmer
        // mennesket i kortet inde i appen.
        val sharedText = intent?.getStringExtra(Intent.EXTRA_TEXT)
        val sharedUri = if (intent?.action == Intent.ACTION_SEND) {
            @Suppress("DEPRECATION")
            intent.getParcelableExtra<android.net.Uri>(Intent.EXTRA_STREAM)?.toString()
        } else {
            null
        }
        val shared = if (intent?.action == Intent.ACTION_SEND) {
            dk.ternedal.modelrig.net.SharedPayload.from(
                text = sharedText,
                subject = intent.getStringExtra(Intent.EXTRA_SUBJECT),
                uri = sharedUri,
                mimeType = intent.type,
                displayName = sharedUri?.let { displayNameOf(android.net.Uri.parse(it)) },
            )
        } else {
            null
        }
        val sharedTruncated = dk.ternedal.modelrig.net.SharedPayload.wasTruncated(sharedText)
        setContent {
            when {
                openSchedules -> {
                    val store = remember { TokenStore(this) }
                    ModelRigTheme(dark = store.darkMode) {
                        ScheduleScreen(store = store, onClose = { finish() })
                    }
                }
                openPersons -> {
                    val store = remember { TokenStore(this) }
                    ModelRigTheme(dark = store.darkMode) {
                        PersonsScreen(store = store, onClose = { finish() })
                    }
                }
                openAgent3Task -> {
                    val store = remember { TokenStore(this) }
                    ModelRigTheme(dark = store.darkMode) {
                        Agent3TaskScreen(
                            store = store,
                            onClose = { finish() },
                            onUseAgent2 = {
                                // Start the ordinary app with no task/developer
                                // extras. The new instance owns normal Agent 2
                                // chat; this shortcut activity then closes.
                                startActivity(Intent(this, MainActivity::class.java))
                                finish()
                            },
                        )
                    }
                }
                openAgent3Capabilities -> {
                    val store = remember { TokenStore(this) }
                    ModelRigTheme(dark = store.darkMode) {
                        Agent3CapabilityScreen(store = store, onClose = { finish() })
                    }
                }
                openAgent3Review -> {
                    val store = remember { TokenStore(this) }
                    ModelRigTheme(dark = store.darkMode) {
                        Agent3ReviewScreen(store = store, onClose = { finish() })
                    }
                }
                openAgent3Replan -> {
                    val store = remember { TokenStore(this) }
                    ModelRigTheme(dark = store.darkMode) {
                        Agent3ReplanScreen(store = store, onClose = { finish() })
                    }
                }
                openAgent3Validation -> {
                    val store = remember { TokenStore(this) }
                    ModelRigTheme(dark = store.darkMode) {
                        Agent3ValidationScreen(store = store, onClose = { finish() })
                    }
                }
                openAgent3Memory -> {
                    val store = remember { TokenStore(this) }
                    ModelRigTheme(dark = store.darkMode) {
                        Agent3MemoryScreen(store = store, onClose = { finish() })
                    }
                }
                openAgent3 -> {
                    val store = remember { TokenStore(this) }
                    ModelRigTheme(dark = store.darkMode) {
                        Agent3Screen(store = store, onClose = { finish() })
                    }
                }
                else -> {
                    val store = remember { TokenStore(this) }
                    AppEntryUi(store, pairingLink, shared, sharedTruncated)
                }
            }
        }
    }

    /** Filens visningsnavn, hvis udbyderen oplyser det. Ellers null — vi gætter ikke. */
    private fun displayNameOf(uri: android.net.Uri): String? = runCatching {
        contentResolver.query(uri, null, null, null, null)?.use { c ->
            val i = c.getColumnIndex(android.provider.OpenableColumns.DISPLAY_NAME)
            if (i >= 0 && c.moveToFirst()) c.getString(i) else null
        }
    }.getOrNull()

    companion object {
        const val EXTRA_SCHEDULES = "dk.ternedal.modelrig.extra.SCHEDULES"
        const val EXTRA_AGENT3_TASK = "dk.ternedal.modelrig.extra.AGENT3_TASK"
        const val EXTRA_PERSONS = "dk.ternedal.modelrig.extra.PERSONS"
        const val EXTRA_AGENT3 = "dk.ternedal.modelrig.extra.AGENT3"
        const val EXTRA_AGENT3_MEMORY = "dk.ternedal.modelrig.extra.AGENT3_MEMORY"
        const val EXTRA_AGENT3_VALIDATION = "dk.ternedal.modelrig.extra.AGENT3_VALIDATION"
        const val EXTRA_AGENT3_CAPABILITIES = "dk.ternedal.modelrig.extra.AGENT3_CAPABILITIES"
        const val EXTRA_AGENT3_REPLAN = "dk.ternedal.modelrig.extra.AGENT3_REPLAN"
        const val EXTRA_AGENT3_REVIEW = "dk.ternedal.modelrig.extra.AGENT3_REVIEW"
    }
}
