package dk.ternedal.modelrig

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.runtime.remember
import androidx.core.splashscreen.SplashScreen.Companion.installSplashScreen
import dk.ternedal.modelrig.data.TokenStore
import dk.ternedal.modelrig.ui.Agent3MemoryScreen
import dk.ternedal.modelrig.ui.Agent3ReplanScreen
import dk.ternedal.modelrig.ui.Agent3ReviewScreen
import dk.ternedal.modelrig.ui.Agent3Screen
import dk.ternedal.modelrig.ui.Agent3ValidationScreen
import dk.ternedal.modelrig.ui.AppUi
import dk.ternedal.modelrig.ui.theme.ModelRigTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        // Must run before super.onCreate: this is what turns the launch into a
        // real Android 12+ splash (ankh on the mode's background) instead of a
        // window-background flash the system splash would paint over.
        installSplashScreen()
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()

        // Developer-only Agent 3.0 entries. The launcher sends none of these
        // extras, so normal users always get AppUi exactly as before. ADB can
        // open each draft explicitly without exporting another activity:
        //
        // adb shell am start -S -n dk.ternedal.modelrig/.MainActivity \
        //   --ez dk.ternedal.modelrig.extra.AGENT3 true
        //
        // adb shell am start -S -n dk.ternedal.modelrig/.MainActivity \
        //   --ez dk.ternedal.modelrig.extra.AGENT3_MEMORY true
        //
        // adb shell am start -S -n dk.ternedal.modelrig/.MainActivity \
        //   --ez dk.ternedal.modelrig.extra.AGENT3_VALIDATION true
        //
        // adb shell am start -S -n dk.ternedal.modelrig/.MainActivity \
        //   --ez dk.ternedal.modelrig.extra.AGENT3_REPLAN true
        //
        // adb shell am start -S -n dk.ternedal.modelrig/.MainActivity \
        //   --ez dk.ternedal.modelrig.extra.AGENT3_REVIEW true
        val openAgent3 = intent?.getBooleanExtra(EXTRA_AGENT3, false) == true
        val openAgent3Memory = intent?.getBooleanExtra(EXTRA_AGENT3_MEMORY, false) == true
        val openAgent3Validation = intent?.getBooleanExtra(EXTRA_AGENT3_VALIDATION, false) == true
        val openAgent3Replan = intent?.getBooleanExtra(EXTRA_AGENT3_REPLAN, false) == true
        val openAgent3Review = intent?.getBooleanExtra(EXTRA_AGENT3_REVIEW, false) == true
        setContent {
            when {
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
                else -> AppUi()
            }
        }
    }

    companion object {
        const val EXTRA_AGENT3 = "dk.ternedal.modelrig.extra.AGENT3"
        const val EXTRA_AGENT3_MEMORY = "dk.ternedal.modelrig.extra.AGENT3_MEMORY"
        const val EXTRA_AGENT3_VALIDATION = "dk.ternedal.modelrig.extra.AGENT3_VALIDATION"
        const val EXTRA_AGENT3_REPLAN = "dk.ternedal.modelrig.extra.AGENT3_REPLAN"
        const val EXTRA_AGENT3_REVIEW = "dk.ternedal.modelrig.extra.AGENT3_REVIEW"
    }
}
