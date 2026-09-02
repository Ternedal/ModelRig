package dk.ternedal.modelrig.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.data.TokenStore
import dk.ternedal.modelrig.net.PersonClient
import dk.ternedal.modelrig.ui.components.kalivScreenInsets
import dk.ternedal.modelrig.ui.theme.KalivTheme
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * Personer (#752): hvem Kaliv er lige nu, og hvem hun kan være.
 *
 * Skærmen læser registret og lader operatøren VÆLGE en person. Den kan ikke
 * aktivere en revision -- det kræver et compatibility-review og sker gennem
 * API'et som en bevidst operatørhandling. Uden valgt person taler Kaliv med
 * klientens sædvanlige persona, og skærmen siger det.
 */
@Composable
fun PersonsScreen(store: TokenStore, onClose: () -> Unit) {
    val scope = rememberCoroutineScope()
    var listing by remember { mutableStateOf<PersonClient.Listing?>(null) }
    var active by remember { mutableStateOf<PersonClient.Active?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }

    fun client() = PersonClient(store.baseUrl.orEmpty(), store.token.orEmpty())

    suspend fun reload() {
        val result = withContext(Dispatchers.IO) {
            runCatching { client().list() to client().active() }
        }
        result.onSuccess { (l, a) -> listing = l; active = a; error = null }
            .onFailure { error = it.message ?: "Kunne ikke hente personer" }
    }

    LaunchedEffect(Unit) { reload() }

    Surface(color = KalivTheme.colors.background, modifier = Modifier.fillMaxSize()) {
        Column(
            Modifier
                .fillMaxSize()
                .kalivScreenInsets()
                .padding(horizontal = 18.dp, vertical = 14.dp)
                .verticalScroll(rememberScrollState()),
        ) {
            dk.ternedal.modelrig.ui.chat.ConversationsTopBar(title = "Personer", onBack = onClose)
            dk.ternedal.modelrig.ui.chat.KnowledgeIntroNote(
                Modifier.padding(bottom = 13.dp),
                text = "Krop, stemme og personlighed aktiveres kun samlet, som en godkendt revision. Her vælger du hvem Kaliv er; aktivering sker på riggen.",
            )

            error?.let {
                PersonCard {
                    Text(it, color = KalivTheme.colors.danger, fontSize = 12.sp)
                }
                Spacer(Modifier.height(12.dp))
            }

            PersonCard {
                Text("Taler lige nu som", fontWeight = FontWeight.SemiBold, color = KalivTheme.colors.textHigh)
                val a = active
                if (a == null) {
                    Text(
                        "Ingen person valgt — Kaliv bruger appens sædvanlige persona.",
                        color = KalivTheme.colors.textMuted, fontSize = 12.sp,
                    )
                } else {
                    Text(a.displayName, color = KalivTheme.colors.textHigh, fontSize = 15.sp)
                    Text(
                        "${a.personRevision} = ${a.bodyId} + ${a.voiceId} + ${a.personalityId}",
                        color = KalivTheme.colors.textMuted, fontSize = 11.sp,
                    )
                    if (a.defaultLanguage.isNotBlank()) {
                        Text("Sprog: ${a.defaultLanguage}", color = KalivTheme.colors.textMuted, fontSize = 11.sp)
                    }
                    if (a.styleNotes.isNotBlank()) {
                        Text("Stil: ${a.styleNotes}", color = KalivTheme.colors.textMuted, fontSize = 11.sp)
                    }
                }
            }
            Spacer(Modifier.height(12.dp))

            val l = listing
            if (l != null && l.persons.isEmpty()) {
                PersonCard {
                    Text("Ingen personer endnu.", color = KalivTheme.colors.textMuted, fontSize = 12.sp)
                    Text(
                        "Opret dem via riggens API — se docs/PERSON_PROFILE.md.",
                        color = KalivTheme.colors.textMuted, fontSize = 11.sp,
                    )
                }
            }
            l?.persons?.forEach { p ->
                val selected = p.personId == l.selectedPersonId
                PersonCard(
                    onClick = if (busy || selected) null else {
                        {
                            busy = true
                            scope.launch {
                                val r = withContext(Dispatchers.IO) { runCatching { client().select(p.personId) } }
                                r.onFailure { error = it.message ?: "Kunne ikke vælge person" }
                                reload()
                                busy = false
                            }
                        }
                    },
                ) {
                    Row(Modifier.fillMaxWidth()) {
                        Text(
                            p.displayName,
                            fontWeight = FontWeight.SemiBold,
                            color = KalivTheme.colors.textHigh,
                            modifier = Modifier.weight(1f),
                        )
                        if (selected) {
                            Text("Valgt", color = KalivTheme.colors.amber, fontSize = 11.sp)
                        }
                    }
                    Text(
                        if (p.activePersonRevision != null) "Aktiv revision: ${p.activePersonRevision}"
                        else "Ingen aktiv revision — kan ikke tale endnu",
                        color = KalivTheme.colors.textMuted, fontSize = 11.sp,
                    )
                    Text(
                        "${p.bodyRevisions} krop · ${p.voiceRevisions} stemme · ${p.personalityRevisions} personlighed · ${p.personRevisions} godkendte",
                        color = KalivTheme.colors.textMuted, fontSize = 11.sp,
                    )
                }
                Spacer(Modifier.height(8.dp))
            }
        }
    }
}

@Composable
private fun PersonCard(onClick: (() -> Unit)? = null, content: @Composable ColumnScope.() -> Unit) {
    val base = Modifier.fillMaxWidth()
    Surface(
        color = KalivTheme.colors.surface,
        shape = RoundedCornerShape(14.dp),
        modifier = if (onClick != null) base.clickable(onClick = onClick) else base,
    ) {
        Column(Modifier.fillMaxWidth().padding(14.dp), content = content)
    }
}
