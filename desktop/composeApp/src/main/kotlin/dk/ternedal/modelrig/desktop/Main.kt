package dk.ternedal.modelrig.desktop

import androidx.compose.ui.res.painterResource
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Window
import androidx.compose.ui.window.application
import androidx.compose.ui.window.rememberWindowState

fun main(args: Array<String>) = application {
    val agent3 = args.contains("--agent3")
    val state = rememberWindowState(
        width = if (agent3) 900.dp else 1000.dp,
        height = 820.dp,
    )
    Window(
        onCloseRequest = ::exitApplication,
        state = state,
        title = if (agent3) "Kaliv · Agent 3.0 draft" else "Kaliv",
        icon = painterResource("icon.png"),
    ) {
        if (agent3) Agent3DevApp() else App()
    }
}
