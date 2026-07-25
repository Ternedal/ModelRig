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
    val agent3Capabilities = args.contains("--agent3-capabilities")
    val agent3Replan = args.contains("--agent3-replan")
    val agent3Review = args.contains("--agent3-review")
    val experimental = agent3 || agent3Memory || agent3Validation ||
        agent3Capabilities || agent3Replan || agent3Review
    // The design frames every direction at 1240x740 (.win in the mockup).
    // At the old 1000dp the 1b cockpit had rail 70 + chat 360 + log 264 = 694
    // and left the plan panel ~250dp, which wrapped "Agent-plan" one letter
    // per line. 1240 gives the plan panel the ~546dp the mockup assumes.
    val state = rememberWindowState(
        width = if (experimental) 900.dp else 1240.dp,
        height = 820.dp,
    )
    Window(
        onCloseRequest = ::exitApplication,
        state = state,
        title = when {
            agent3Capabilities -> "Kaliv · Agent 3.0 Capability Graph"
            agent3Review -> "Kaliv · Agent 3.0 Read Review"
            agent3Replan -> "Kaliv · Agent 3.0 Read Replanner"
            agent3Validation -> "Kaliv · Agent 3.0 Validation Center"
            agent3Memory -> "Kaliv · Memory 3.0 draft"
            agent3 -> "Kaliv · Agent 3.0 draft"
            else -> "Kaliv"
        },
        icon = painterResource("icon.png"),
    ) {
        when {
            agent3Capabilities -> Agent3CapabilityDevApp()
            agent3Review -> Agent3ReviewDevApp()
            agent3Replan -> Agent3ReplanDevApp()
            agent3Validation -> Agent3ValidationDevApp()
            agent3Memory -> Agent3MemoryDevApp()
            agent3 -> Agent3DevApp()
            else -> App()
        }
    }
}
