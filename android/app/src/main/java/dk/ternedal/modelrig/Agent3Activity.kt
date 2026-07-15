package dk.ternedal.modelrig

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.runtime.remember
import dk.ternedal.modelrig.data.TokenStore
import dk.ternedal.modelrig.ui.Agent3Screen
import dk.ternedal.modelrig.ui.theme.ModelRigTheme

/**
 * Developer-only host for the Agent 3.0 draft.
 *
 * The activity is non-exported and has no launcher/deep-link entry. It exists so
 * the isolated Agent 3.0 API can be exercised on the actual phone without
 * touching the production ChatScreen routing.
 */
class Agent3Activity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            val store = remember { TokenStore(this) }
            ModelRigTheme(dark = store.darkMode) {
                Agent3Screen(store = store, onClose = { finish() })
            }
        }
    }
}
