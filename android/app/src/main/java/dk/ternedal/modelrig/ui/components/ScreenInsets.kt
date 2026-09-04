package dk.ternedal.modelrig.ui.components

import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.statusBars
import androidx.compose.foundation.layout.union
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier

/**
 * Systemlinje-afstand for en HEL skærm.
 *
 * Appen kører kant-til-kant (enableEdgeToEdge i MainActivity), så en skærm
 * der bare fylder vinduet tegner ind under statuslinjen og navigationslinjen.
 * Det så Anders på sin Pixel 15/08: Rig-status' titel lå oven i uret.
 *
 * Hver skærm skal derfor selv holde afstand. Denne modifier er den ene måde
 * at gøre det på — den er navngivet, så nye skærme kan finde den, og så en
 * gate kan kræve den (tests/workflow_screen_insets.py).
 */
@Composable
fun Modifier.kalivScreenInsets(): Modifier =
    this.windowInsetsPadding(WindowInsets.statusBars.union(WindowInsets.navigationBars))
