package dk.ternedal.modelrig.desktop

import androidx.compose.foundation.background
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
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.desktop.data.DesktopChatDb
import dk.ternedal.modelrig.desktop.net.Agent3Memory
import dk.ternedal.modelrig.desktop.net.Agent3MemoryClient
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * Developer-only Memory 3.0 administration UI.
 *
 * It is opened only with --agent3-memory and never injects memory into a model,
 * planner or ordinary chat request.
 */
@Composable
fun Agent3MemoryDevApp() {
    val db = remember { DesktopChatDb() }
    fun setting(key: String, env: String?, default: String): String =
        System.getenv(env ?: "")?.takeIf { it.isNotBlank() }
            ?: db.getSetting(key) ?: default

    var darkMode by remember { mutableStateOf(db.getSetting("darkMode") != "false") }
    KalivTheme(dark = darkMode) {
        val scope = rememberCoroutineScope()
        var baseUrl by remember {
            mutableStateOf(
                System.getenv("MODELRIG_AGENT3_URL")?.takeIf { it.isNotBlank() }
                    ?: setting("localUrl", "MODELRIG_LOCAL_URL", "http://127.0.0.1:8080")
            )
        }
        var token by remember { mutableStateOf(setting("deviceToken", "MODELRIG_TOKEN", "")) }
        var query by remember { mutableStateOf("") }
        var subjectFilter by remember { mutableStateOf("") }
        var memories by remember { mutableStateOf<List<Agent3Memory>>(emptyList()) }
        var history by remember { mutableStateOf<List<Agent3Memory>>(emptyList()) }
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
            require(baseUrl.isNotBlank()) { "Base-URL mangler" }
            require(token.isNotBlank()) { "Device-token mangler" }
            return Agent3MemoryClient(baseUrl.trim(), token.trim())
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
                    notice = "${it.size} memories hentet. Ingen data er sendt til en model."
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

        fun review(memory: Agent3Memory, confirm: Boolean) {
            execute(
                action = { if (confirm) client().confirm(memory.id) else client().reject(memory.id) },
                success = {
                    memories = memories.map { row -> if (row.id == it.id) it else row }
                    notice = if (confirm) "Memory bekræftet." else "Memory afvist."
                },
                fallback = "Review kunne ikke gemmes",
            )
        }

        fun beginCorrection(memory: Agent3Memory) {
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

        fun loadHistory(memory: Agent3Memory) {
            execute(
                action = { client().history(memory.id) },
                success = {
                    history = it
                    historyTitle = "${memory.subject} · ${memory.predicate}"
                },
                fallback = "Historikken kunne ikke hentes",
            )
        }

        fun deleteMemory(memory: Agent3Memory) {
            if (pendingDeleteId != memory.id) {
                pendingDeleteId = memory.id
                notice = "Tryk Bekræft sletning for at fjerne værdien og oprette en tombstone."
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

        Column(
            Modifier
                .fillMaxSize()
                .background(KalivTheme.colors.Graphite)
                .padding(20.dp)
                .verticalScroll(rememberScrollState()),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("Memory 3.0", color = KalivTheme.colors.TextHigh, fontSize = 28.sp, fontWeight = FontWeight.Bold)
                    Text(
                        "Eksperimentel administration · --agent3-memory · ingen automatisk modelbrug",
                        color = KalivTheme.colors.TextMuted,
                        fontSize = 12.sp,
                    )
                }
                OutlinedButton(onClick = { darkMode = !darkMode }) { Text(if (darkMode) "Lys" else "Mørk") }
            }

            Spacer(Modifier.height(14.dp))
            MemoryDevCard {
                Text("Forbindelse", color = KalivTheme.colors.TextHigh, fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    value = baseUrl,
                    onValueChange = { baseUrl = it },
                    label = { Text("ModelRig backend-URL") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    value = token,
                    onValueChange = { token = it },
                    label = { Text("Device-token") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
            }

            Spacer(Modifier.height(12.dp))
            MemoryDevCard {
                Text("Opret eksplicit memory", color = KalivTheme.colors.TextHigh, fontWeight = FontWeight.SemiBold)
                Text("Remote secrets understøttes bevidst ikke.", color = KalivTheme.colors.TextMuted, fontSize = 11.sp)
                Spacer(Modifier.height(8.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(
                        value = createSubject,
                        onValueChange = { createSubject = it },
                        label = { Text("Subject") },
                        singleLine = true,
                        modifier = Modifier.weight(1f),
                    )
                    OutlinedTextField(
                        value = createPredicate,
                        onValueChange = { createPredicate = it },
                        label = { Text("Predicate") },
                        singleLine = true,
                        modifier = Modifier.weight(1f),
                    )
                }
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    value = createValue,
                    onValueChange = { createValue = it },
                    label = { Text("Værdi") },
                    minLines = 2,
                    maxLines = 6,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    value = createKind,
                    onValueChange = { createKind = it },
                    label = { Text("Kind: fact, preference, project, relationship, routine, constraint eller note") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(8.dp))
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
                MemoryDevCard {
                    Text("Ret memory", color = KalivTheme.colors.TextHigh, fontWeight = FontWeight.SemiBold)
                    Text("Rettelsen opretter en ny version og superseder den gamle.", color = KalivTheme.colors.TextMuted, fontSize = 11.sp)
                    Spacer(Modifier.height(8.dp))
                    OutlinedTextField(
                        value = editValue,
                        onValueChange = { editValue = it },
                        label = { Text("Ny værdi") },
                        minLines = 2,
                        maxLines = 8,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Spacer(Modifier.height(8.dp))
                    SensitivityButtons(editSensitivity) { editSensitivity = it }
                    Spacer(Modifier.height(10.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(enabled = !busy && editValue.isNotBlank(), onClick = ::saveCorrection) { Text("Gem ny version") }
                        OutlinedButton(onClick = { editId = null; editValue = "" }) { Text("Annullér") }
                    }
                }
            }

            Spacer(Modifier.height(12.dp))
            MemoryDevCard {
                Text("Find memories", color = KalivTheme.colors.TextHigh, fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    value = query,
                    onValueChange = { query = it },
                    label = { Text("Fritekstsøgning; tomt felt viser listen") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(8.dp))
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
                MemoryDevCard { Text(it, color = KalivTheme.colors.Danger, fontSize = 13.sp) }
            }
            notice?.let {
                Spacer(Modifier.height(12.dp))
                MemoryDevCard { Text(it, color = KalivTheme.colors.Signal, fontSize = 13.sp) }
            }

            if (memories.isNotEmpty()) {
                Spacer(Modifier.height(12.dp))
                Text("Resultater", color = KalivTheme.colors.TextHigh, fontSize = 18.sp, fontWeight = FontWeight.Bold)
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
                MemoryDevCard {
                    Text("Historik · $title", color = KalivTheme.colors.TextHigh, fontWeight = FontWeight.Bold)
                    Spacer(Modifier.height(8.dp))
                    history.forEachIndexed { index, item ->
                        Text(
                            "${index + 1}. ${item.lifecycleStatus} / ${item.reviewStatus} · ${item.value.ifBlank { "[slettet]" }}",
                            color = KalivTheme.colors.TextHigh,
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
private fun MemoryDevCard(content: @Composable ColumnScope.() -> Unit) {
    Column(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(KalivTheme.colors.Surface)
            .padding(14.dp),
        content = content,
    )
}

@Composable
private fun SensitivityButtons(selected: String, onSelected: (String) -> Unit) {
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        listOf("public" to "Public", "operational" to "Operational", "private" to "Private").forEach { (value, label) ->
            if (selected == value) Button(onClick = { onSelected(value) }) { Text(label) }
            else OutlinedButton(onClick = { onSelected(value) }) { Text(label) }
        }
    }
}

@Composable
private fun MemoryRecordCard(
    memory: Agent3Memory,
    busy: Boolean,
    deleteArmed: Boolean,
    onConfirm: () -> Unit,
    onReject: () -> Unit,
    onEdit: () -> Unit,
    onHistory: () -> Unit,
    onDelete: () -> Unit,
) {
    MemoryDevCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("${memory.subject} · ${memory.predicate}", color = KalivTheme.colors.TextHigh, fontWeight = FontWeight.Bold)
                Text(memory.id, color = KalivTheme.colors.TextMuted, fontSize = 9.sp)
            }
            Text("${memory.reviewStatus} / ${memory.sensitivity}", color = KalivTheme.colors.Signal, fontSize = 11.sp)
        }
        Spacer(Modifier.height(7.dp))
        Text(memory.value.ifBlank { "[slettet]" }, color = KalivTheme.colors.TextHigh, fontSize = 13.sp)
        Spacer(Modifier.height(5.dp))
        Text(
            "kind=${memory.kind} · source=${memory.sourceType} · confidence=${"%.2f".format(memory.confidence)}",
            color = KalivTheme.colors.TextMuted,
            fontSize = 10.sp,
        )
        memory.sourceRef?.let { Text(it, color = KalivTheme.colors.TextMuted, fontSize = 9.sp) }
        Spacer(Modifier.height(10.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(7.dp)) {
            if (memory.reviewStatus == "pending" && memory.lifecycleStatus == "active") {
                Button(enabled = !busy, onClick = onConfirm) { Text("Bekræft") }
                OutlinedButton(enabled = !busy, onClick = onReject) { Text("Afvis") }
            }
            if (memory.reviewStatus == "confirmed" && memory.lifecycleStatus == "active") {
                OutlinedButton(enabled = !busy, onClick = onEdit) { Text("Ret") }
            }
            OutlinedButton(enabled = !busy, onClick = onHistory) { Text("Historik") }
            if (memory.lifecycleStatus == "active") {
                OutlinedButton(enabled = !busy, onClick = onDelete) {
                    Text(if (deleteArmed) "Bekræft sletning" else "Slet")
                }
            }
        }
    }
}
