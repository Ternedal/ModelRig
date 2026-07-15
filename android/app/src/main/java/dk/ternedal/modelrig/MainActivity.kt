package dk.ternedal.modelrig

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.runtime.remember
import androidx.core.splashscreen.SplashScreen.Companion.installSplashScreen
import dk.ternedal.modelrig.data.TokenStore
import dk.ternedal.modelrig.ui.Agent3MemoryScreen
import dk.ternedal.modelrig.ui.Agent3Screen
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

        // Developer-only Agent 3.0 entries. The launcher sends neither extra, so
        // normal users always get AppUi exactly as before. ADB can open either
        // draft explicitly without exporting a second activity:
        //
        // adb shell am start -S -n dk.ternedal.modelrig/.MainActivity \
        //   --ez dk.ternedal.modelrig.extra.AGENT3 true
        //
        // adb shell am start -S -n dk.ternedal.modelrig/.MainActivity \
        //   --ez dk.ternedal.modelrig.extra.AGENT3_MEMORY true
        val openAgent3 = intent?.getBooleanExtra(EXTRA_AGENT3, false) == true
        val openAgent3Memory = intent?.getBooleanExtra(EXTRA_AGENT3_MEMORY, false) == true
        setContent {
            when {
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
    }
}
