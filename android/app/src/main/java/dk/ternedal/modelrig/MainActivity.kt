package dk.ternedal.modelrig

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
        // Scheduler is a human-facing app shortcut; Agent 3 entries remain
        // developer-only ADB surfaces until their own readiness gates say otherwise.
        val openSchedules =
            intent?.getBooleanExtra(EXTRA_SCHEDULES, false) == true ||
                (intent?.data?.scheme == "kaliv" && intent?.data?.host == "schedules")
        val openAgent3 = intent?.getBooleanExtra(EXTRA_AGENT3, false) == true
        val openAgent3Memory = intent?.getBooleanExtra(EXTRA_AGENT3_MEMORY, false) == true
        val openAgent3Validation = intent?.getBooleanExtra(EXTRA_AGENT3_VALIDATION, false) == true
        val openAgent3Capabilities = intent?.getBooleanExtra(EXTRA_AGENT3_CAPABILITIES, false) == true
        val openAgent3Replan = intent?.getBooleanExtra(EXTRA_AGENT3_REPLAN, false) == true
        val openAgent3Review = intent?.getBooleanExtra(EXTRA_AGENT3_REVIEW, false) == true
        setContent {
            when {
                openSchedules -> {
                    val store = remember { TokenStore(this) }
                    ModelRigTheme(dark = store.darkMode) {
                        ScheduleScreen(store = store, onClose = { finish() })
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
                    AppEntryUi(store)
                }
            }
        }
    }

    companion object {
        const val EXTRA_SCHEDULES = "dk.ternedal.modelrig.extra.SCHEDULES"
        const val EXTRA_AGENT3 = "dk.ternedal.modelrig.extra.AGENT3"
        const val EXTRA_AGENT3_MEMORY = "dk.ternedal.modelrig.extra.AGENT3_MEMORY"
        const val EXTRA_AGENT3_VALIDATION = "dk.ternedal.modelrig.extra.AGENT3_VALIDATION"
        const val EXTRA_AGENT3_CAPABILITIES = "dk.ternedal.modelrig.extra.AGENT3_CAPABILITIES"
        const val EXTRA_AGENT3_REPLAN = "dk.ternedal.modelrig.extra.AGENT3_REPLAN"
        const val EXTRA_AGENT3_REVIEW = "dk.ternedal.modelrig.extra.AGENT3_REVIEW"
    }
}
