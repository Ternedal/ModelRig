package dk.kaliv.visionrig.producer

import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.nio.file.AtomicMoveNotSupportedException
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import kotlinx.serialization.Serializable
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json

@Serializable
data class ProducerState(
    val schemaId: String = "visionrig/native-producer-state/v1",
    val nextSequence: Long = 0,
    val pendingDropped: Long = 0,
    val inflightSequence: Long? = null,
) {
    fun validate() {
        require(schemaId == "visionrig/native-producer-state/v1")
        require(nextSequence >= 0)
        require(pendingDropped >= 0)
        require(inflightSequence == null || inflightSequence < nextSequence)
    }
}

data class FrameReservation(
    val sequence: Long,
    val pendingDropped: Long,
)

interface ProducerStateStore {
    fun recover(): ProducerState
    fun reserve(): FrameReservation
    fun markDropped(sequence: Long): ProducerState
    fun markAccepted(sequence: Long): ProducerState
    fun snapshot(): ProducerState
}

class FileProducerStateStore(
    private val file: File,
    private val json: Json = Json {
        ignoreUnknownKeys = false
        encodeDefaults = true
    },
) : ProducerStateStore {
    private val lock = Any()

    override fun recover(): ProducerState = synchronized(lock) {
        val current = load()
        val inflight = current.inflightSequence ?: return@synchronized current
        check(inflight < current.nextSequence)
        val recovered = current.copy(
            pendingDropped = current.pendingDropped + 1,
            inflightSequence = null,
        )
        save(recovered)
        recovered
    }

    override fun reserve(): FrameReservation = synchronized(lock) {
        val current = load()
        check(current.inflightSequence == null) {
            "producer state has an in-flight frame; recover before reserve"
        }
        val sequence = current.nextSequence
        val reserved = current.copy(
            nextSequence = sequence + 1,
            inflightSequence = sequence,
        )
        save(reserved)
        FrameReservation(sequence, current.pendingDropped)
    }

    override fun markDropped(sequence: Long): ProducerState = synchronized(lock) {
        val current = load()
        check(current.inflightSequence == sequence) {
            "drop does not match in-flight sequence"
        }
        val updated = current.copy(
            pendingDropped = current.pendingDropped + 1,
            inflightSequence = null,
        )
        save(updated)
        updated
    }

    override fun markAccepted(sequence: Long): ProducerState = synchronized(lock) {
        val current = load()
        check(current.inflightSequence == sequence) {
            "accept does not match in-flight sequence"
        }
        val updated = current.copy(
            pendingDropped = 0,
            inflightSequence = null,
        )
        save(updated)
        updated
    }

    override fun snapshot(): ProducerState = synchronized(lock) { load() }

    private fun load(): ProducerState {
        if (!file.exists()) return ProducerState()
        val text = try {
            file.readText(Charsets.UTF_8)
        } catch (exc: IOException) {
            throw ProducerProtocolException(
                "unable to read producer state file",
                exc,
            )
        }
        if (text.isBlank()) {
            throw ProducerProtocolException("producer state file is empty")
        }
        val state = try {
            json.decodeFromString<ProducerState>(text).also { it.validate() }
        } catch (exc: Exception) {
            throw ProducerProtocolException("invalid producer state file", exc)
        }
        return state
    }

    private fun save(state: ProducerState) {
        state.validate()
        val parent = file.absoluteFile.parentFile
            ?: throw ProducerProtocolException("producer state has no parent directory")
        if (!parent.exists() && !parent.mkdirs()) {
            throw ProducerProtocolException("unable to create producer state directory")
        }
        val temp = File(parent, "." + file.name + "." + System.nanoTime() + ".tmp")
        try {
            try {
                FileOutputStream(temp).use { out ->
                    out.write(
                        (json.encodeToString(state) + "\n")
                            .toByteArray(Charsets.UTF_8)
                    )
                    out.flush()
                    out.fd.sync()
                }
                try {
                    Files.move(
                        temp.toPath(),
                        file.toPath(),
                        StandardCopyOption.ATOMIC_MOVE,
                        StandardCopyOption.REPLACE_EXISTING,
                    )
                } catch (_: AtomicMoveNotSupportedException) {
                    Files.move(
                        temp.toPath(),
                        file.toPath(),
                        StandardCopyOption.REPLACE_EXISTING,
                    )
                }
            } catch (exc: IOException) {
                throw ProducerProtocolException(
                    "unable to persist producer state file",
                    exc,
                )
            }
        } finally {
            if (temp.exists()) temp.delete()
        }
    }
}
