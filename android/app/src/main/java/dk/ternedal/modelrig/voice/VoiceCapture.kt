package dk.ternedal.modelrig.voice

import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioRecord
import android.media.AudioTrack
import android.media.MediaRecorder
import java.io.ByteArrayOutputStream

/**
 * Alva Voice: microphone capture and playback for push-to-talk.
 *
 * Records 16 kHz mono PCM16 (what the rig's ASR expects) and wraps it in a WAV
 * container for upload. Plays a WAV reply back through AudioTrack.
 *
 * NOT YET TESTED ON A DEVICE. AudioRecord/AudioTrack behaviour varies across
 * OEMs and requires the RECORD_AUDIO runtime permission; this can only be
 * verified on Anders' phone. Kept deliberately small: one recorder, one player,
 * whole-utterance (no live streaming, no barge-in -- those are later).
 */
class VoiceCapture {
    private val sampleRate = 16000
    private var recorder: AudioRecord? = null
    @Volatile private var recording = false
    private var recordThread: Thread? = null
    private val pcm = ByteArrayOutputStream()

    /** Begin capturing from the mic. Caller must hold RECORD_AUDIO permission. */
    fun start() {
        if (recording) return
        pcm.reset()
        val minBuf = AudioRecord.getMinBufferSize(
            sampleRate, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT,
        ).coerceAtLeast(4096)
        val rec = AudioRecord(
            MediaRecorder.AudioSource.MIC,
            sampleRate,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
            minBuf,
        )
        recorder = rec
        recording = true
        rec.startRecording()
        recordThread = Thread {
            val buf = ByteArray(minBuf)
            while (recording) {
                val n = rec.read(buf, 0, buf.size)
                if (n > 0) pcm.write(buf, 0, n)
            }
        }.also { it.start() }
    }

    /**
     * Stop capturing and return the recording as a 16 kHz mono WAV byte array,
     * or null if nothing was captured.
     */
    fun stopToWav(): ByteArray? {
        if (!recording) return null
        recording = false
        recordThread?.join(1000)
        recordThread = null
        recorder?.let {
            try { it.stop() } catch (_: Exception) {}
            it.release()
        }
        recorder = null
        val pcmBytes = pcm.toByteArray()
        if (pcmBytes.isEmpty()) return null
        return wrapPcmAsWav(pcmBytes, sampleRate, channels = 1, bitsPerSample = 16)
    }

    fun cancel() {
        recording = false
        recordThread?.join(500)
        recordThread = null
        recorder?.let { try { it.stop() } catch (_: Exception) {}; it.release() }
        recorder = null
        pcm.reset()
    }

    companion object {
        /** Prepend a 44-byte WAV header to raw PCM. */
        fun wrapPcmAsWav(pcm: ByteArray, sampleRate: Int, channels: Int, bitsPerSample: Int): ByteArray {
            val byteRate = sampleRate * channels * bitsPerSample / 8
            val blockAlign = channels * bitsPerSample / 8
            val dataLen = pcm.size
            val totalLen = 36 + dataLen
            val header = ByteArray(44)
            fun putStr(off: Int, s: String) { for (i in s.indices) header[off + i] = s[i].code.toByte() }
            fun putIntLE(off: Int, v: Int) {
                header[off] = (v and 0xff).toByte()
                header[off + 1] = ((v shr 8) and 0xff).toByte()
                header[off + 2] = ((v shr 16) and 0xff).toByte()
                header[off + 3] = ((v shr 24) and 0xff).toByte()
            }
            fun putShortLE(off: Int, v: Int) {
                header[off] = (v and 0xff).toByte()
                header[off + 1] = ((v shr 8) and 0xff).toByte()
            }
            putStr(0, "RIFF"); putIntLE(4, totalLen); putStr(8, "WAVE")
            putStr(12, "fmt "); putIntLE(16, 16); putShortLE(20, 1); putShortLE(22, channels)
            putIntLE(24, sampleRate); putIntLE(28, byteRate); putShortLE(32, blockAlign)
            putShortLE(34, bitsPerSample); putStr(36, "data"); putIntLE(40, dataLen)
            return header + pcm
        }

        /**
         * Play a WAV byte array (any sample rate; reads it from the header)
         * through AudioTrack. Blocks until playback finishes. Piper replies are
         * typically 22.05 kHz mono PCM16.
         */
        /**
         * Play a WAV byte array (any sample rate; reads it from the header)
         * through AudioTrack. Blocks until playback finishes. Piper replies are
         * typically 22.05 kHz mono PCM16.
         *
         * If [bargeIn] is supplied, playback is interruptible: the detector
         * listens on the mic while Alva speaks, and playback stops the moment
         * the user starts talking. Returns true if it was interrupted.
         *
         * Uses MODE_STREAM (not MODE_STATIC) precisely so the write loop can
         * check for a barge-in between chunks. MODE_STATIC hands the whole
         * buffer to the hardware and can't be stopped cleanly mid-utterance.
         */
        fun playWav(wav: ByteArray, bargeIn: BargeInDetector? = null): Boolean {
            if (wav.size <= 44) return false
            fun intLE(off: Int) = (wav[off].toInt() and 0xff) or
                ((wav[off + 1].toInt() and 0xff) shl 8) or
                ((wav[off + 2].toInt() and 0xff) shl 16) or
                ((wav[off + 3].toInt() and 0xff) shl 24)
            fun shortLE(off: Int) = (wav[off].toInt() and 0xff) or ((wav[off + 1].toInt() and 0xff) shl 8)
            val channels = shortLE(22)
            val rate = intLE(24)
            val chMask = if (channels >= 2) AudioFormat.CHANNEL_OUT_STEREO else AudioFormat.CHANNEL_OUT_MONO
            val pcm = wav.copyOfRange(44, wav.size)
            val minBuf = AudioTrack.getMinBufferSize(rate, chMask, AudioFormat.ENCODING_PCM_16BIT)
                .coerceAtLeast(4096)
            val track = AudioTrack(
                AudioManager.STREAM_MUSIC,
                rate, chMask, AudioFormat.ENCODING_PCM_16BIT,
                minBuf, AudioTrack.MODE_STREAM,
            )
            var interrupted = false
            try {
                track.play()
                bargeIn?.start()
                // Write in chunks so we can bail out between them. Chunk size is
                // the device's minimum buffer: small enough to react quickly,
                // large enough not to underrun.
                var off = 0
                while (off < pcm.size) {
                    if (bargeIn?.triggered == true) { interrupted = true; break }
                    val n = minOf(minBuf, pcm.size - off)
                    val written = track.write(pcm, off, n)
                    if (written <= 0) break
                    off += written
                }
                if (!interrupted) {
                    // Let the tail drain rather than cutting the last syllable.
                    val remainingMs = 200L
                    val deadline = System.currentTimeMillis() + remainingMs
                    while (System.currentTimeMillis() < deadline) {
                        if (bargeIn?.triggered == true) { interrupted = true; break }
                        Thread.sleep(20)
                    }
                }
            } finally {
                bargeIn?.stop()
                try { track.pause(); track.flush(); track.stop() } catch (_: Exception) {}
                track.release()
            }
            return interrupted
        }
    }
}

/**
 * Listens on the microphone while Alva is speaking and reports when the user
 * starts talking, so playback can be cut short (barge-in).
 *
 * Echo cancellation: the mic would otherwise hear Alva's own voice through the
 * speaker and trigger constantly. Two defences, both OS-level:
 *   1. AudioSource.VOICE_COMMUNICATION -- the source phone calls use, which
 *      asks the platform for AEC/NS/AGC.
 *   2. AcousticEchoCanceler attached to the session, when the device offers it.
 * Quality is OEM-dependent. On a headset there's no echo to cancel and this is
 * trivially reliable; on a speaker it depends on the phone's AEC. If the device
 * has no AEC, [available] is false and callers can require a headset.
 *
 * Detection is a simple energy gate with a hangover: RMS must exceed a
 * threshold for several consecutive frames, so a door slam or a click doesn't
 * cut Alva off mid-sentence.
 *
 * NOT TESTED ON A DEVICE. The threshold in particular is a starting point that
 * likely needs calibrating against a real phone and a real speaker.
 */
class BargeInDetector(
    private val sampleRate: Int = 16000,
    /** RMS above this (0..32767 scale) counts as speech. Needs on-device tuning. */
    private val rmsThreshold: Double = 1500.0,
    /** Consecutive loud frames required before we call it speech. */
    private val framesToTrigger: Int = 3,
) {
    @Volatile var triggered = false
        private set

    /** True if the platform gave us an echo canceler. On speaker, this matters. */
    var echoCancelerEnabled = false
        private set

    private var record: AudioRecord? = null
    private var aec: android.media.audiofx.AcousticEchoCanceler? = null
    private var thread: Thread? = null
    @Volatile private var running = false

    /** Whether this device offers acoustic echo cancellation at all. */
    val available: Boolean
        get() = android.media.audiofx.AcousticEchoCanceler.isAvailable()

    fun start() {
        if (running) return
        triggered = false
        val minBuf = AudioRecord.getMinBufferSize(
            sampleRate, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT,
        ).coerceAtLeast(2048)
        val rec = try {
            AudioRecord(
                // VOICE_COMMUNICATION (not MIC): asks the platform for AEC/NS/AGC.
                MediaRecorder.AudioSource.VOICE_COMMUNICATION,
                sampleRate, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT,
                minBuf,
            )
        } catch (_: Exception) {
            return  // no mic permission or device busy -- barge-in simply won't fire
        }
        if (rec.state != AudioRecord.STATE_INITIALIZED) { rec.release(); return }
        record = rec
        if (android.media.audiofx.AcousticEchoCanceler.isAvailable()) {
            aec = runCatching {
                android.media.audiofx.AcousticEchoCanceler.create(rec.audioSessionId)?.also {
                    it.enabled = true
                    echoCancelerEnabled = it.enabled
                }
            }.getOrNull()
        }
        running = true
        rec.startRecording()
        thread = Thread {
            val buf = ShortArray(minBuf / 2)
            var loudFrames = 0
            while (running && !triggered) {
                val n = rec.read(buf, 0, buf.size)
                if (n <= 0) continue
                var sum = 0.0
                for (i in 0 until n) { val v = buf[i].toDouble(); sum += v * v }
                val rms = kotlin.math.sqrt(sum / n)
                if (rms > rmsThreshold) {
                    loudFrames++
                    if (loudFrames >= framesToTrigger) triggered = true
                } else {
                    loudFrames = 0
                }
            }
        }.also { it.start() }
    }

    fun stop() {
        running = false
        thread?.join(300)
        thread = null
        aec?.let { runCatching { it.enabled = false; it.release() } }
        aec = null
        record?.let {
            runCatching { it.stop() }
            it.release()
        }
        record = null
    }
}
