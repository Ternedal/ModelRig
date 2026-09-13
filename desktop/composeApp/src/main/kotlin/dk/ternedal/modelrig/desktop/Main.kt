package dk.ternedal.modelrig.desktop

import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Window
import androidx.compose.ui.window.application
import androidx.compose.ui.window.rememberWindowState

fun main(args: Array<String>) = application {
    val tasks = args.contains("--tasks")
    val agent3 = args.contains("--agent3")
    val agent3Memory = args.contains("--agent3-memory")
    val agent3Validation = args.contains("--agent3-validation")
    val agent3Capabilities = args.contains("--agent3-capabilities")
    val agent3Replan = args.contains("--agent3-replan")
    val agent3Review = args.contains("--agent3-review")
    val experimental = agent3 || agent3Memory || agent3Validation ||
        agent3Capabilities || agent3Replan || agent3Review
    var showTasks by remember { mutableStateOf(tasks) }
    var forceNormalChat by remember { mutableStateOf(false) }

    val sizing = desktopWindowSizing(
        showTasks = showTasks,
        experimental = experimental,
        forceNormalChat = forceNormalChat,
    )

    // The design frames every normal direction at 1240x740 (.win in the
    // mockup). Developer evidence surfaces stay narrow. WindowState controls
    // the initial size only; the native minimum below prevents the fixed shell
    // columns from squeezing the flexible work area into an unusable sliver.
    val state = rememberWindowState(
        width = sizing.initialWidthDp.dp,
        height = sizing.initialHeightDp.dp,
    )
    Window(
        onCloseRequest = ::exitApplication,
        state = state,
        title = when {
            showTasks -> "Kaliv · Opgaver"
            forceNormalChat -> "Kaliv"
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
        // Compose desktop and AWT top-level windows both expose logical screen
        // coordinates. Do not multiply this policy by LocalDensity: that would
        // double-scale the minimum on HiDPI displays. SideEffect keeps the
        // native floor in sync when a task/dev surface falls back to normal.
        val nativeMinimum = remember(
            sizing.minimumWidthDp,
            sizing.minimumHeightDp,
        ) {
            sizing.awtMinimumSize()
        }
        SideEffect {
            if (window.minimumSize != nativeMinimum) {
                window.minimumSize = nativeMinimum
            }
        }

        when {
            showTasks -> Agent3TaskApp(
                onUseAgent2 = {
                    showTasks = false
                    forceNormalChat = true
                },
            )
            forceNormalChat -> App()
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
