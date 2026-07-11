package dk.ternedal.modelrig

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.core.splashscreen.SplashScreen.Companion.installSplashScreen
import dk.ternedal.modelrig.ui.AppUi

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        // Must run before super.onCreate: this is what turns the launch into a
        // real Android 12+ splash (ankh on the mode's background) instead of a
        // window-background flash the system splash would paint over.
        installSplashScreen()
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent { AppUi() }
    }
}
