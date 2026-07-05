package dk.ternedal.modelrig.desktop

import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Window
import androidx.compose.ui.window.application
import androidx.compose.ui.window.rememberWindowState

fun main() = application {
    val state = rememberWindowState(width = 1000.dp, height = 820.dp)
    Window(onCloseRequest = ::exitApplication, state = state, title = "ModelRig") {
        App()
    }
}
