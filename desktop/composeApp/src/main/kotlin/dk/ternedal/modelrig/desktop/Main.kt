package dk.ternedal.modelrig.desktop

import androidx.compose.ui.res.painterResource
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Window
import androidx.compose.ui.window.application
import androidx.compose.ui.window.rememberWindowState

fun main(args: Array<String>) = application {
    val agent3 = args.contains("--agent3")
    val agent3Memory = args.contains("--agent3-memory")
    val agent3Validation = args.contains("--agent3-validation")
    val agent3Replan = args.contains("--agent3-replan")
    val experimental = agent3 || agent3Memory || agent3Validation || agent3Replan
    val state = rememberWindowState(
        width = if (experimental) 900.dp else 1000.dp,
        height = 820.dp,
    )
    Window(
        onCloseRequest = ::exitApplication,
        state = state,
        title = when {
            agent3Replan -> "Kaliv · Agent 3.0 Read Replanner"
            agent3Validation -> "Kaliv · Agent 3.0 Validation Center"
            agent3Memory -> "Kaliv · Memory 3.0 draft"
            agent3 -> "Kaliv · Agent 3.0 draft"
            else -> "Kaliv"
        },
        icon = painterResource("icon.png"),
    ) {
        when {
            agent3Replan -> Agent3ReplanDevApp()
            agent3Validation -> Agent3ValidationDevApp()
            agent3Memory -> Agent3MemoryDevApp()
            agent3 -> Agent3DevApp()
            else -> App()
        }
    }
}
