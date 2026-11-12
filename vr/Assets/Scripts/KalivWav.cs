using System;
using System.IO;
using System.Text;

namespace Kaliv.VR
{
    /// <summary>Decoded PCM, ready for an AudioClip.</summary>
    public sealed class KalivPcm
    {
        public float[] Samples;      // interleaved, -1..1
        public int Channels;
        public int SampleRate;
        public float Seconds => SampleRate > 0 && Channels > 0 ? (float)Samples.Length / Channels / SampleRate : 0f;
    }

    /// <summary>
    /// WAV in and out, for the voice turn.
    ///
    /// Up: the rig's ASR expects 16 kHz mono 16-bit (Android's voiceConverseStream sends
    /// exactly that), while the Quest microphone records at whatever rate the device picks —
    /// so the capture is resampled here rather than trusting the device.
    ///
    /// Down: the TTS sentences are WAV files from the worker. The header is READ, not
    /// assumed — the rate and format are the TTS backend's choice and differ between
    /// backends, and a clip built at the wrong rate plays as chipmunk or slow-motion speech.
    /// </summary>
    public static class KalivWav
    {
        public const int RigSampleRate = 16000;

        /// <summary>Mono float samples at <paramref name="sourceRate"/> → 16 kHz mono PCM16 WAV.</summary>
        public static byte[] EncodeForRig(float[] mono, int sourceRate)
        {
            if (mono == null) throw new ArgumentNullException(nameof(mono));
            float[] s = sourceRate == RigSampleRate ? mono : Resample(mono, sourceRate, RigSampleRate);
            return EncodePcm16(s, 1, RigSampleRate);
        }

        public static byte[] EncodePcm16(float[] interleaved, int channels, int sampleRate)
        {
            int dataBytes = interleaved.Length * 2;
            using var ms = new MemoryStream(44 + dataBytes);
            using var w = new BinaryWriter(ms);
            w.Write(Encoding.ASCII.GetBytes("RIFF"));
            w.Write(36 + dataBytes);
            w.Write(Encoding.ASCII.GetBytes("WAVE"));
            w.Write(Encoding.ASCII.GetBytes("fmt "));
            w.Write(16);                          // fmt chunk size
            w.Write((short)1);                    // PCM
            w.Write((short)channels);
            w.Write(sampleRate);
            w.Write(sampleRate * channels * 2);   // byte rate
            w.Write((short)(channels * 2));       // block align
            w.Write((short)16);                   // bits
            w.Write(Encoding.ASCII.GetBytes("data"));
            w.Write(dataBytes);
            foreach (float f in interleaved)
            {
                float c = f < -1f ? -1f : (f > 1f ? 1f : f);
                w.Write((short)Math.Round(c * 32767f));
            }
            w.Flush();
            return ms.ToArray();
        }

        /// <summary>
        /// Linear resampling. Speech for ASR does not need a polyphase filter; it needs the
        /// right rate. Downsampling 48 kHz → 16 kHz linearly is what most mobile ASR
        /// front-ends tolerate fine.
        /// </summary>
        public static float[] Resample(float[] src, int fromRate, int toRate)
        {
            if (fromRate <= 0 || toRate <= 0) throw new ArgumentException("rates must be positive");
            if (src.Length == 0 || fromRate == toRate) return (float[])src.Clone();
            int n = (int)Math.Max(1, Math.Round((long)src.Length * toRate / (double)fromRate));
            var dst = new float[n];
            double step = (double)fromRate / toRate;
            for (int i = 0; i < n; i++)
            {
                double pos = i * step;
                int a = (int)pos;
                if (a >= src.Length - 1) { dst[i] = src[src.Length - 1]; continue; }
                float t = (float)(pos - a);
                dst[i] = src[a] + (src[a + 1] - src[a]) * t;
            }
            return dst;
        }

        /// <summary>
        /// Decode a RIFF/WAVE file: PCM 8/16/24/32-bit integer, or IEEE float 32-bit.
        /// Unknown chunks (LIST, fact …) are skipped by their declared size. Throws
        /// FormatException on anything else — playing garbage as audio is worse than silence.
        /// </summary>
        public static KalivPcm Decode(byte[] wav)
        {
            if (wav == null || wav.Length < 12) throw new FormatException("not a WAV file (too short)");
            if (Encoding.ASCII.GetString(wav, 0, 4) != "RIFF" || Encoding.ASCII.GetString(wav, 8, 4) != "WAVE")
                throw new FormatException("not a RIFF/WAVE file");

            int format = 0, channels = 0, rate = 0, bits = 0;
            int pos = 12;
            int dataStart = -1, dataLen = 0;
            while (pos + 8 <= wav.Length)
            {
                string id = Encoding.ASCII.GetString(wav, pos, 4);
                int size = BitConverter.ToInt32(wav, pos + 4);
                int body = pos + 8;
                if (size < 0) throw new FormatException("negative chunk size");

                if (id == "fmt ")
                {
                    if (size < 16 || body + 16 > wav.Length) throw new FormatException("short fmt chunk");
                    format = BitConverter.ToInt16(wav, body);
                    channels = BitConverter.ToInt16(wav, body + 2);
                    rate = BitConverter.ToInt32(wav, body + 4);
                    bits = BitConverter.ToInt16(wav, body + 14);
                    // WAVE_FORMAT_EXTENSIBLE carries the real format in its sub-format GUID.
                    if (format == unchecked((short)0xFFFE) && size >= 26 && body + 26 <= wav.Length)
                        format = BitConverter.ToInt16(wav, body + 24);
                }
                else if (id == "data")
                {
                    dataStart = body;
                    // Streaming writers sometimes leave the size at 0 or 0xFFFFFFFF; take what is there.
                    dataLen = size == 0 || body + size > wav.Length ? wav.Length - body : size;
                    break;
                }
                pos = body + size + (size & 1);   // chunks are word-aligned
            }

            if (channels <= 0 || rate <= 0) throw new FormatException("WAV has no usable fmt chunk");
            if (dataStart < 0) throw new FormatException("WAV has no data chunk");

            int bytesPer = bits / 8;
            if (bytesPer <= 0) throw new FormatException("unsupported bit depth " + bits);
            int count = dataLen / bytesPer;
            var samples = new float[count - count % channels];

            for (int i = 0; i < samples.Length; i++)
            {
                int o = dataStart + i * bytesPer;
                if (format == 3 && bits == 32) samples[i] = BitConverter.ToSingle(wav, o);
                else if (format == 1 && bits == 16) samples[i] = BitConverter.ToInt16(wav, o) / 32768f;
                else if (format == 1 && bits == 8) samples[i] = (wav[o] - 128) / 128f;
                else if (format == 1 && bits == 24)
                {
                    int v = wav[o] | (wav[o + 1] << 8) | (wav[o + 2] << 16);
                    if ((v & 0x800000) != 0) v |= unchecked((int)0xFF000000);
                    samples[i] = v / 8388608f;
                }
                else if (format == 1 && bits == 32) samples[i] = BitConverter.ToInt32(wav, o) / 2147483648f;
                else throw new FormatException($"unsupported WAV format {format}/{bits}-bit");
            }

            return new KalivPcm { Samples = samples, Channels = channels, SampleRate = rate };
        }

        /// <summary>Peak level 0..1, for the "Kaliv hears you" indicator and a silence check.</summary>
        public static float Peak(float[] s, int start = 0, int count = -1)
        {
            if (s == null) return 0f;
            int end = count < 0 ? s.Length : Math.Min(s.Length, start + count);
            float p = 0f;
            for (int i = Math.Max(0, start); i < end; i++)
            {
                float a = s[i] < 0 ? -s[i] : s[i];
                if (a > p) p = a;
            }
            return p;
        }
    }
}
