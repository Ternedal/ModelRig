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
        fun playWav(wav: ByteArray) {
            if (wav.size <= 44) return
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
                .coerceAtLeast(pcm.size)
            val track = AudioTrack(
                AudioManager.STREAM_MUSIC,
                rate, chMask, AudioFormat.ENCODING_PCM_16BIT,
                minBuf, AudioTrack.MODE_STATIC,
            )
            track.write(pcm, 0, pcm.size)
            track.play()
            // MODE_STATIC plays the written buffer once; wait for it to drain.
            val durationMs = (pcm.size.toLong() * 1000L) / (rate.toLong() * channels * 2)
            Thread.sleep(durationMs + 200)
            try { track.stop() } catch (_: Exception) {}
            track.release()
        }
    }
}
