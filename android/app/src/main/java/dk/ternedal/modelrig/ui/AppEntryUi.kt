package dk.ternedal.modelrig.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.data.TokenStore
import dk.ternedal.modelrig.logic.AppEntryDestination
import dk.ternedal.modelrig.logic.CredentialCondition
import dk.ternedal.modelrig.logic.SourceAvailability
import dk.ternedal.modelrig.ui.theme.KalivTheme
import dk.ternedal.modelrig.ui.theme.ModelRigTheme

/**
 * Small entry boundary in front of the AppUi monolith.
 *
 * Normal launches still go directly to AppUi. Only the otherwise ambiguous
 * state -- no usable source, but unreadable encrypted credentials -- gets an
 * explicit recovery screen instead of looking like a fresh installation.
 */
@Composable
fun AppEntryUi(store: TokenStore) {
    val initialSources = remember {
        SourceAvailability.from(
            store.rigCredentialStatus,
            store.cloudCredentialStatus,
        )
    }
    var continueToApp by remember {
        mutableStateOf(
            initialSources.entryDestination != AppEntryDestination.SETUP ||
                !initialSources.hasInvalidCredentials,
        )
    }

    if (continueToApp) {
        AppUi()
        return
    }

    ModelRigTheme(dark = store.darkMode) {
        CredentialRecoveryScreen(
            invalidRig = initialSources.rig == CredentialCondition.INVALID,
            invalidCloud = initialSources.cloud == CredentialCondition.INVALID,
            onContinue = { continueToApp = true },
            onClear = {
                val rigCleared =
                    initialSources.rig != CredentialCondition.INVALID || store.clearRig()
                val cloudCleared =
                    initialSources.cloud != CredentialCondition.INVALID || store.clearCloud()
                val cleared = rigCleared && cloudCleared
                if (cleared) continueToApp = true
                cleared
            },
        )
    }
}

@Composable
private fun CredentialRecoveryScreen(
    invalidRig: Boolean,
    invalidCloud: Boolean,
    onContinue: () -> Unit,
    onClear: () -> Boolean,
) {
    var clearFailed by remember { mutableStateOf(false) }
    val affected = when {
        invalidRig && invalidCloud -> "rig- og cloud-adgangen"
        invalidRig -> "rig-adgangen"
        else -> "cloud-adgangen"
    }

    Surface(
        color = KalivTheme.colors.background,
        modifier = Modifier.fillMaxSize(),
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(24.dp),
            verticalArrangement = Arrangement.Center,
            horizontalAlignment = Alignment.Start,
        ) {
            Surface(
                color = KalivTheme.colors.surface,
                shape = RoundedCornerShape(16.dp),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Column(Modifier.padding(20.dp)) {
                    Text(
                        "Gemt adgang kan ikke læses",
                        color = KalivTheme.colors.textHigh,
                        fontSize = 22.sp,
                        fontWeight = FontWeight.Bold,
                    )
                    Spacer(Modifier.height(10.dp))
                    Text(
                        "Android kan ikke længere dekryptere $affected. Det sker typisk efter gendannelse eller flytning til en anden enhed. Indtast adgangsoplysningerne igen i opsætningen.",
                        color = KalivTheme.colors.textMuted,
                        fontSize = 14.sp,
                        lineHeight = 20.sp,
                    )
                    Spacer(Modifier.height(18.dp))
                    Button(
                        onClick = onContinue,
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text("Gå til opsætning")
                    }
                    Spacer(Modifier.height(8.dp))
                    OutlinedButton(
                        onClick = { clearFailed = !onClear() },
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text("Ryd gamle credentials")
                    }
                    if (clearFailed) {
                        Spacer(Modifier.height(8.dp))
                        Text(
                            "De gamle credentials kunne ikke ryddes. Prøv igen eller overskriv dem i opsætningen.",
                            color = KalivTheme.colors.danger,
                            fontSize = 12.sp,
                        )
                    }
                }
            }
        }
    }
}
