package dk.ternedal.modelrig.desktop

import androidx.compose.ui.res.painterResource
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Window
import androidx.compose.ui.window.application
import androidx.compose.ui.window.rememberWindowState

fun main(args: Array<String>) = application {
    val agent3 = args.contains("--agent3")
    val agent3Memory = args.contains("--agent3-memory")
    val experimental = agent3 || agent3Memory
    val state = rememberWindowState(
        width = if (experimental) 900.dp else 1000.dp,
        height = 820.dp,
    )
    Window(
        onCloseRequest = ::exitApplication,
        state = state,
        title = when {
            agent3Memory -> "Kaliv · Memory 3.0 draft"
            agent3 -> "Kaliv · Agent 3.0 draft"
            else -> "Kaliv"
        },
        icon = painterResource("icon.png"),
    ) {
        when {
            agent3Memory -> Agent3MemoryDevApp()
            agent3 -> Agent3DevApp()
            else -> App()
        }
    }
}
