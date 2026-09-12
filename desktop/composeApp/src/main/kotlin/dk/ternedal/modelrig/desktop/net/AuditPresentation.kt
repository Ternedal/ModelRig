package dk.ternedal.modelrig.desktop.net

/**
 * Convert machine-oriented audit summaries into bounded operator copy without
 * mutating the raw evidence received from the rig.
 *
 * Most tools already return prose. `rig_status` is the deliberate exception:
 * its result is a newline-delimited key=value payload because models and
 * diagnostics consume it. The desktop UI must not promote those internal keys
 * directly into Handlingslog.
 */
internal fun desktopAuditOperatorSummary(tool: String, rawSummary: String): String {
    val raw = rawSummary.trim()
    if (raw.isEmpty()) return ""
    if (tool.trim().lowercase() != "rig_status") return raw

    val fields = raw.lineSequence()
        .mapNotNull { line ->
            val split = line.indexOf('=')
            if (split <= 0) null
            else line.substring(0, split).trim() to line.substring(split + 1).trim()
        }
        .toMap()

    if (fields.isEmpty()) return "Rigstatus registreret."

    fun availability(value: String): String = when (value.trim().lowercase()) {
        "true" -> "tilgængelig"
        "false" -> "ikke tilgængelig"
        else -> "ukendt"
    }

    return buildList {
        fields["disk_free_gb"]?.takeIf { it.isNotBlank() }?.let {
            add("Ledig diskplads: $it GB")
        }
        fields["disk_total_gb"]?.takeIf { it.isNotBlank() }?.let {
            add("Disk i alt: $it GB")
        }
        fields["gpu"]?.takeIf { it.isNotBlank() }?.let {
            add("GPU: ${if (it.equals("unavailable", ignoreCase = true)) "ikke tilgængelig" else it}")
        }
        fields["asr_available"]?.let {
            add("Talegenkendelse: ${availability(it)}")
        }
        if (fields["asr_available"]?.equals("true", ignoreCase = true) == true) {
            fields["asr_device"]?.takeIf { it.isNotBlank() }?.let {
                add("Talegenkendelse kører på: $it")
            }
            fields["asr_model"]?.takeIf { it.isNotBlank() }?.let {
                add("Talegenkendelsesmodel: $it")
            }
        }
        fields["tts_available"]?.let {
            add("Talesyntese: ${availability(it)}")
        }
    }.ifEmpty {
        listOf("Rigstatus registreret.")
    }.joinToString("\n")
}
