package dk.ternedal.modelrig.ui

import androidx.compose.foundation.layout.Arrangement
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
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.data.TokenStore
import dk.ternedal.modelrig.net.Agent3MemoryClient
import dk.ternedal.modelrig.ui.theme.KalivTheme
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** Developer-only Memory 3.0 UI. No memory is sent to a model from this screen. */
@Composable
fun Agent3MemoryScreen(store: TokenStore, onClose: () -> Unit) {
    val scope = rememberCoroutineScope()
    var query by remember { mutableStateOf("") }
    var subjectFilter by remember { mutableStateOf("") }
    var memories by remember { mutableStateOf<List<Agent3MemoryClient.Memory>>(emptyList()) }
    var history by remember { mutableStateOf<List<Agent3MemoryClient.Memory>>(emptyList()) }
    var historyTitle by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var notice by remember { mutableStateOf<String?>(null) }

    var createSubject by remember { mutableStateOf("") }
    var createPredicate by remember { mutableStateOf("") }
    var createValue by remember { mutableStateOf("") }
    var createKind by remember { mutableStateOf("fact") }
    var createSensitivity by remember { mutableStateOf("private") }

    var editId by remember { mutableStateOf<String?>(null) }
    var editValue by remember { mutableStateOf("") }
    var editSensitivity by remember { mutableStateOf("private") }
    var pendingDeleteId by remember { mutableStateOf<String?>(null) }

    fun client(): Agent3MemoryClient {
        val base = store.baseUrl?.takeIf { it.isNotBlank() } ?: error("Ingen rig-URL er gemt")
        val token = store.token?.takeIf { it.isNotBlank() } ?: error("Ingen device-token er gemt")
        return Agent3MemoryClient(base, token)
    }

    fun <T> execute(action: () -> T, success: (T) -> Unit, fallback: String) {
        if (busy) return
        busy = true
        error = null
        notice = null
        scope.launch {
            val result = withContext(Dispatchers.IO) { runCatching(action) }
            busy = false
            result.onSuccess(success).onFailure { error = it.message ?: fallback }
        }
    }

    fun loadMemories() {
        execute(
            action = {
                val found = if (query.isBlank()) client().list(subjectFilter.ifBlank { null })
                else client().search(query)
                if (subjectFilter.isBlank()) found else found.filter { it.subject == subjectFilter.trim() }
            },
            success = {
                memories = it
                history = emptyList()
                historyTitle = null
                notice = "${it.size} memories hentet. Intet er sendt til en model."
            },
            fallback = "Memories kunne ikke hentes",
        )
    }

    fun createMemory() {
        val subject = createSubject.trim()
        val predicate = createPredicate.trim()
        val value = createValue.trim()
        val kind = createKind.trim()
        if (subject.isEmpty() || predicate.isEmpty() || value.isEmpty() || kind.isEmpty()) return
        execute(
            action = { client().create(subject, predicate, value, kind, createSensitivity) },
            success = {
                createSubject = ""
                createPredicate = ""
                createValue = ""
                memories = listOf(it) + memories.filterNot { row -> row.id == it.id }
                notice = "Memory oprettet som eksplicit og bekræftet."
            },
            fallback = "Memory kunne ikke oprettes",
        )
    }

    fun review(memory: Agent3MemoryClient.Memory, confirm: Boolean) {
        execute(
            action = { if (confirm) client().confirm(memory.id) else client().reject(memory.id) },
            success = {
                memories = memories.map { row -> if (row.id == it.id) it else row }
                notice = if (confirm) "Memory bekræftet." else "Memory afvist."
            },
            fallback = "Review kunne ikke gemmes",
        )
    }

    fun beginCorrection(memory: Agent3MemoryClient.Memory) {
        editId = memory.id
        editValue = memory.value
        editSensitivity = memory.sensitivity
        pendingDeleteId = null
    }

    fun saveCorrection() {
        val id = editId ?: return
        val value = editValue.trim()
        if (value.isEmpty()) return
        execute(
            action = { client().correct(id, value, editSensitivity) },
            success = {
                memories = listOf(it) + memories.filterNot { row -> row.id == id || row.id == it.id }
                editId = null
                editValue = ""
                notice = "Rettelsen blev gemt som en ny version."
            },
            fallback = "Rettelsen kunne ikke gemmes",
        )
    }

    fun loadHistory(memory: Agent3MemoryClient.Memory) {
        execute(
            action = { client().history(memory.id) },
            success = {
                history = it
                historyTitle = "${memory.subject} · ${memory.predicate}"
            },
            fallback = "Historikken kunne ikke hentes",
        )
    }

    fun deleteMemory(memory: Agent3MemoryClient.Memory) {
        if (pendingDeleteId != memory.id) {
            pendingDeleteId = memory.id
            notice = "Tryk Bekræft sletning for at fjerne værdien og bevare en tombstone."
            return
        }
        execute(
            action = { client().delete(memory.id) },
            success = {
                memories = memories.filterNot { row -> row.id == memory.id }
                pendingDeleteId = null
                if (editId == memory.id) editId = null
                notice = "Memory-værdien er slettet; kun en indholdsfri tombstone er bevaret."
            },
            fallback = "Memory kunne ikke slettes",
        )
    }

    Surface(color = KalivTheme.colors.background, modifier = Modifier.fillMaxSize()) {
        Column(
            Modifier
                .fillMaxSize()
                .padding(horizontal = 18.dp, vertical = 14.dp)
                .verticalScroll(rememberScrollState()),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("Memory 3.0", fontSize = 26.sp, fontWeight = FontWeight.Bold, color = KalivTheme.colors.textHigh)
                    Text(
                        "Eksperimentel administration · ingen automatisk modelbrug",
                        fontSize = 12.sp,
                        color = KalivTheme.colors.textMuted,
                    )
                }
                TextButton(onClick = onClose) { Text("Luk", color = KalivTheme.colors.signal) }
            }

            Spacer(Modifier.height(14.dp))
            MemoryCard {
                Text("Opret eksplicit memory", fontWeight = FontWeight.SemiBold, color = KalivTheme.colors.textHigh)
                Text("Remote secrets understøttes bevidst ikke.", color = KalivTheme.colors.textMuted, fontSize = 11.sp)
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    value = createSubject,
                    onValueChange = { createSubject = it },
                    label = { Text("Subject") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(7.dp))
                OutlinedTextField(
                    value = createPredicate,
                    onValueChange = { createPredicate = it },
                    label = { Text("Predicate") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(7.dp))
                OutlinedTextField(
                    value = createValue,
                    onValueChange = { createValue = it },
                    label = { Text("Værdi") },
                    minLines = 2,
                    maxLines = 6,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(7.dp))
                OutlinedTextField(
                    value = createKind,
                    onValueChange = { createKind = it },
                    label = { Text("Kind") },
                    supportingText = { Text("fact, preference, project, relationship, routine, constraint eller note") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(7.dp))
                SensitivityButtons(createSensitivity) { createSensitivity = it }
                Spacer(Modifier.height(10.dp))
                Button(
                    enabled = !busy && createSubject.isNotBlank() && createPredicate.isNotBlank() &&
                        createValue.isNotBlank() && createKind.isNotBlank(),
                    onClick = ::createMemory,
                ) { Text(if (busy) "Arbejder…" else "Opret memory") }
            }

            editId?.let {
                Spacer(Modifier.height(12.dp))
                MemoryCard {
                    Text("Ret memory", fontWeight = FontWeight.SemiBold, color = KalivTheme.colors.textHigh)
                    Text("Der oprettes en ny version; den gamle supersedes.", color = KalivTheme.colors.textMuted, fontSize = 11.sp)
                    Spacer(Modifier.height(8.dp))
                    OutlinedTextField(
                        value = editValue,
                        onValueChange = { editValue = it },
                        label = { Text("Ny værdi") },
                        minLines = 2,
                        maxLines = 7,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Spacer(Modifier.height(7.dp))
                    SensitivityButtons(editSensitivity) { editSensitivity = it }
                    Spacer(Modifier.height(10.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(enabled = !busy && editValue.isNotBlank(), onClick = ::saveCorrection) { Text("Gem ny version") }
                        OutlinedButton(onClick = { editId = null; editValue = "" }) { Text("Annullér") }
                    }
                }
            }

            Spacer(Modifier.height(12.dp))
            MemoryCard {
                Text("Find memories", fontWeight = FontWeight.SemiBold, color = KalivTheme.colors.textHigh)
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    value = query,
                    onValueChange = { query = it },
                    label = { Text("Fritekstsøgning; tomt felt viser listen") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(7.dp))
                OutlinedTextField(
                    value = subjectFilter,
                    onValueChange = { subjectFilter = it },
                    label = { Text("Valgfrit præcist subject-filter") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(10.dp))
                Button(enabled = !busy, onClick = ::loadMemories) { Text(if (busy) "Arbejder…" else "Hent memories") }
            }

            error?.let {
                Spacer(Modifier.height(12.dp))
                MemoryCard { Text(it, color = KalivTheme.colors.danger, fontSize = 13.sp) }
            }
            notice?.let {
                Spacer(Modifier.height(12.dp))
                MemoryCard { Text(it, color = KalivTheme.colors.success, fontSize = 13.sp) }
            }

            if (memories.isNotEmpty()) {
                Spacer(Modifier.height(12.dp))
                Text("Resultater", color = KalivTheme.colors.textHigh, fontSize = 18.sp, fontWeight = FontWeight.Bold)
                Spacer(Modifier.height(7.dp))
                memories.forEach { memory ->
                    MemoryRecordCard(
                        memory = memory,
                        busy = busy,
                        deleteArmed = pendingDeleteId == memory.id,
                        onConfirm = { review(memory, true) },
                        onReject = { review(memory, false) },
                        onEdit = { beginCorrection(memory) },
                        onHistory = { loadHistory(memory) },
                        onDelete = { deleteMemory(memory) },
                    )
                    Spacer(Modifier.height(8.dp))
                }
            }

            historyTitle?.let { title ->
                Spacer(Modifier.height(8.dp))
                MemoryCard {
                    Text("Historik · $title", color = KalivTheme.colors.textHigh, fontWeight = FontWeight.Bold)
                    Spacer(Modifier.height(8.dp))
                    history.forEachIndexed { index, item ->
                        Text(
                            "${index + 1}. ${item.lifecycleStatus} / ${item.reviewStatus} · ${item.value.ifBlank { "[slettet]" }}",
                            color = KalivTheme.colors.textHigh,
                            fontSize = 12.sp,
                        )
                        if (index != history.lastIndex) HorizontalDivider(Modifier.padding(vertical = 6.dp))
                    }
                }
            }
            Spacer(Modifier.height(24.dp))
        }
    }
}

@Composable
private fun MemoryCard(content: @Composable ColumnScope.() -> Unit) {
    Surface(color = KalivTheme.colors.surface, shape = RoundedCornerShape(14.dp), modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.fillMaxWidth().padding(14.dp), content = content)
    }
}

@Composable
private fun SensitivityButtons(selected: String, onSelected: (String) -> Unit) {
    Row(horizontalArrangement = Arrangement.spacedBy(7.dp)) {
        listOf("public" to "Public", "operational" to "Operational", "private" to "Private").forEach { (value, label) ->
            if (selected == value) Button(onClick = { onSelected(value) }) { Text(label) }
            else OutlinedButton(onClick = { onSelected(value) }) { Text(label) }
        }
    }
}

@Composable
private fun MemoryRecordCard(
    memory: Agent3MemoryClient.Memory,
    busy: Boolean,
    deleteArmed: Boolean,
    onConfirm: () -> Unit,
    onReject: () -> Unit,
    onEdit: () -> Unit,
    onHistory: () -> Unit,
    onDelete: () -> Unit,
) {
    MemoryCard {
        Text("${memory.subject} · ${memory.predicate}", color = KalivTheme.colors.textHigh, fontWeight = FontWeight.Bold)
        Text(memory.id, color = KalivTheme.colors.textMuted, fontSize = 9.sp)
        Spacer(Modifier.height(5.dp))
        Text(memory.value.ifBlank { "[slettet]" }, color = KalivTheme.colors.textHigh, fontSize = 13.sp)
        Spacer(Modifier.height(5.dp))
        Text(
            "${memory.reviewStatus} / ${memory.lifecycleStatus} · ${memory.sensitivity} · ${memory.kind}",
            color = KalivTheme.colors.accent,
            fontSize = 10.sp,
        )
        Text(
            "source=${memory.sourceType} · confidence=${"%.2f".format(memory.confidence)}",
            color = KalivTheme.colors.textMuted,
            fontSize = 10.sp,
        )
        Spacer(Modifier.height(9.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            if (memory.reviewStatus == "pending" && memory.lifecycleStatus == "active") {
                Button(enabled = !busy, onClick = onConfirm) { Text("Bekræft") }
                OutlinedButton(enabled = !busy, onClick = onReject) { Text("Afvis") }
            }
            if (memory.reviewStatus == "confirmed" && memory.lifecycleStatus == "active") {
                OutlinedButton(enabled = !busy, onClick = onEdit) { Text("Ret") }
            }
            OutlinedButton(enabled = !busy, onClick = onHistory) { Text("Historik") }
        }
        if (memory.lifecycleStatus == "active") {
            Spacer(Modifier.height(6.dp))
            OutlinedButton(enabled = !busy, onClick = onDelete) {
                Text(if (deleteArmed) "Bekræft sletning" else "Slet")
            }
        }
    }
}
