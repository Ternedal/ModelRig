using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using UnityEngine;

namespace ModelRig.BodyRig.UnityRenderer
{
    /// <summary>
    /// Machine-only live quality collector. It receives only frames that have
    /// already passed BodyRigFrameSource validation AND renderer.Apply(), then
    /// grades the live integration sequence. The fixture physical proof owns
    /// static renderer mapping (gaze/state visuals); this probe owns what is
    /// unique to the product/live path: state transitions, speech-envelope mouth,
    /// interruption neutralization and continuous blink/breath motion.
    /// </summary>
    [DefaultExecutionOrder(1500)]
    public sealed class BodyRigLiveQualityProbe : MonoBehaviour
    {
        private const string ReceiptSchema = "bodyrig.unity_live_quality/v0.1";
        private const string ReceiptEnvironment = "BODYRIG_LIVE_QUALITY_RECEIPT";
        private const int MinAppliedFrames = 80;
        private const long MinDurationMs = 5000;
        private const int MinSpeakingFrames = 2;
        private const int MinInterruptedFrames = 2;
        private const float MinSpeakingMouthActivity = 0.10f;
        private const float MaxInterruptedMouthActivity = 0.01f;
        private const float MinBlinkPeak = 0.50f;
        private const float MinBreathRange = 0.05f;

        [Serializable]
        private sealed class Thresholds
        {
            public int min_applied_frames = MinAppliedFrames;
            public long min_duration_ms = MinDurationMs;
            public int min_speaking_frames = MinSpeakingFrames;
            public int min_interrupted_frames = MinInterruptedFrames;
            public float min_speaking_mouth_activity = MinSpeakingMouthActivity;
            public float max_interrupted_mouth_activity = MaxInterruptedMouthActivity;
            public float min_blink_peak = MinBlinkPeak;
            public float min_breath_range = MinBreathRange;
        }

        [Serializable]
        private sealed class Checks
        {
            public bool required_states_seen;
            public bool enough_applied_frames;
            public bool enough_duration;
            public bool live_speech_mouth_active;
            public bool interruption_mouth_neutral;
            public bool interruption_gesture_neutral;
            public bool blink_active;
            public bool breath_active;
        }

        [Serializable]
        private sealed class QualityReceipt
        {
            public string schema = ReceiptSchema;
            public string created_at;
            public bool production_activation = false;
            public string candidate_git_sha;
            public string body_id;
            public string package_sha256;
            public string source_url;
            public string[] required_states;
            public string[] states_seen;
            public int applied_frames;
            public long first_timestamp_ms;
            public long last_timestamp_ms;
            public long duration_ms;
            public int speaking_frames;
            public float max_speaking_mouth_open;
            public float max_speaking_viseme_weight;
            public int interrupted_frames;
            public float max_interrupted_mouth_open;
            public float max_interrupted_viseme_weight;
            public int interrupted_nonempty_gesture_frames;
            public float blink_min;
            public float blink_max;
            public float breath_min;
            public float breath_max;
            public Thresholds thresholds = new Thresholds();
            public Checks checks;
            public bool machine_quality_pass;
        }

        private static readonly string[] RequiredStates =
        {
            "idle",
            "listening",
            "speaking",
            "interrupted",
        };

        private readonly HashSet<string> statesSeen = new HashSet<string>(StringComparer.Ordinal);
        private bool hasFrame;
        private bool sawInterrupted;
        private bool receiptAttempted;
        private int appliedFrames;
        private long firstTimestampMs;
        private long lastTimestampMs;
        private int speakingFrames;
        private float maxSpeakingMouthOpen;
        private float maxSpeakingVisemeWeight;
        private int interruptedFrames;
        private float maxInterruptedMouthOpen;
        private float maxInterruptedVisemeWeight;
        private int interruptedNonemptyGestureFrames;
        private float blinkMin = 1.0f;
        private float blinkMax;
        private float breathMin = 1.0f;
        private float breathMax;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        private static void Install()
        {
            if (string.IsNullOrWhiteSpace(Environment.GetEnvironmentVariable(ReceiptEnvironment)))
            {
                return;
            }
            if (FindObjectOfType<BodyRigLiveQualityProbe>() != null)
            {
                return;
            }
            var host = new GameObject("BodyRig Live Quality Probe");
            DontDestroyOnLoad(host);
            host.AddComponent<BodyRigLiveQualityProbe>();
        }

        private void OnEnable()
        {
            BodyRigFrameSource.FrameApplied += OnFrameApplied;
        }

        private void OnDisable()
        {
            BodyRigFrameSource.FrameApplied -= OnFrameApplied;
        }

        private void OnFrameApplied(BodyRigRenderFrame frame)
        {
            if (frame == null || receiptAttempted)
            {
                return;
            }
            frame.Validate();
            if (!hasFrame)
            {
                hasFrame = true;
                firstTimestampMs = frame.timestamp_ms;
            }
            lastTimestampMs = frame.timestamp_ms;
            appliedFrames++;
            statesSeen.Add(frame.state);
            blinkMin = Mathf.Min(blinkMin, frame.blink);
            blinkMax = Mathf.Max(blinkMax, frame.blink);
            breathMin = Mathf.Min(breathMin, frame.breath);
            breathMax = Mathf.Max(breathMax, frame.breath);

            var visemePeak = 0.0f;
            if (frame.visemes != null)
            {
                foreach (var viseme in frame.visemes)
                {
                    if (viseme != null)
                    {
                        visemePeak = Mathf.Max(visemePeak, viseme.weight);
                    }
                }
            }

            if (frame.state == "speaking")
            {
                speakingFrames++;
                maxSpeakingMouthOpen = Mathf.Max(maxSpeakingMouthOpen, frame.mouth_open);
                maxSpeakingVisemeWeight = Mathf.Max(maxSpeakingVisemeWeight, visemePeak);
            }
            if (frame.state == "interrupted")
            {
                sawInterrupted = true;
                interruptedFrames++;
                maxInterruptedMouthOpen = Mathf.Max(maxInterruptedMouthOpen, frame.mouth_open);
                maxInterruptedVisemeWeight = Mathf.Max(maxInterruptedVisemeWeight, visemePeak);
                if (!string.IsNullOrEmpty(frame.gesture))
                {
                    interruptedNonemptyGestureFrames++;
                }
            }

            // The proof driver explicitly returns to idle after giving the
            // renderer enough interrupted frames. That transition is our
            // deterministic end-of-exercise marker: write one create-only PASS
            // or FAIL receipt with the raw measurements, never a rolling file.
            if (sawInterrupted && frame.state == "idle")
            {
                CommitReceipt();
            }
        }

        private void CommitReceipt()
        {
            if (receiptAttempted)
            {
                return;
            }
            receiptAttempted = true;
            var pathRaw = Environment.GetEnvironmentVariable(ReceiptEnvironment);
            if (string.IsNullOrWhiteSpace(pathRaw))
            {
                return;
            }

            var requiredStatesSeen = RequiredStates.All(statesSeen.Contains);
            var durationMs = hasFrame ? Math.Max(0, lastTimestampMs - firstTimestampMs) : 0;
            var mouthActivity = Mathf.Max(maxSpeakingMouthOpen, maxSpeakingVisemeWeight);
            var interruptedActivity = Mathf.Max(maxInterruptedMouthOpen, maxInterruptedVisemeWeight);
            var checks = new Checks
            {
                required_states_seen = requiredStatesSeen,
                enough_applied_frames = appliedFrames >= MinAppliedFrames,
                enough_duration = durationMs >= MinDurationMs,
                live_speech_mouth_active = speakingFrames >= MinSpeakingFrames && mouthActivity >= MinSpeakingMouthActivity,
                interruption_mouth_neutral = interruptedFrames >= MinInterruptedFrames && interruptedActivity <= MaxInterruptedMouthActivity,
                interruption_gesture_neutral = interruptedFrames >= MinInterruptedFrames && interruptedNonemptyGestureFrames == 0,
                blink_active = blinkMax >= MinBlinkPeak,
                breath_active = (breathMax - breathMin) >= MinBreathRange,
            };
            var pass = checks.required_states_seen
                && checks.enough_applied_frames
                && checks.enough_duration
                && checks.live_speech_mouth_active
                && checks.interruption_mouth_neutral
                && checks.interruption_gesture_neutral
                && checks.blink_active
                && checks.breath_active;

            var report = new QualityReceipt
            {
                created_at = DateTimeOffset.UtcNow.ToString("o"),
                candidate_git_sha = RequireEnvironment("BODYRIG_CANDIDATE_SHA"),
                body_id = RequireEnvironment("BODYRIG_BODY_ID"),
                package_sha256 = RequireEnvironment("BODYRIG_PACKAGE_SHA256"),
                source_url = RequireEnvironment("BODYRIG_RIG_URL").TrimEnd('/'),
                required_states = RequiredStates,
                states_seen = statesSeen.OrderBy(value => value, StringComparer.Ordinal).ToArray(),
                applied_frames = appliedFrames,
                first_timestamp_ms = firstTimestampMs,
                last_timestamp_ms = lastTimestampMs,
                duration_ms = durationMs,
                speaking_frames = speakingFrames,
                max_speaking_mouth_open = maxSpeakingMouthOpen,
                max_speaking_viseme_weight = maxSpeakingVisemeWeight,
                interrupted_frames = interruptedFrames,
                max_interrupted_mouth_open = maxInterruptedMouthOpen,
                max_interrupted_viseme_weight = maxInterruptedVisemeWeight,
                interrupted_nonempty_gesture_frames = interruptedNonemptyGestureFrames,
                blink_min = blinkMin,
                blink_max = blinkMax,
                breath_min = breathMin,
                breath_max = breathMax,
                checks = checks,
                machine_quality_pass = pass,
            };

            try
            {
                var path = Path.GetFullPath(pathRaw);
                if (File.Exists(path) || Directory.Exists(path))
                {
                    throw new IOException("BodyRig live quality receipt destination already exists.");
                }
                var directory = Path.GetDirectoryName(path);
                if (string.IsNullOrWhiteSpace(directory) || !Directory.Exists(directory))
                {
                    throw new DirectoryNotFoundException("BodyRig live quality receipt directory does not exist.");
                }
                var raw = Encoding.UTF8.GetBytes(JsonUtility.ToJson(report, false));
                var temporary = path + ".tmp-" + Guid.NewGuid().ToString("N");
                try
                {
                    using (var stream = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                    {
                        stream.Write(raw, 0, raw.Length);
                        stream.Flush(true);
                    }
                    if (File.Exists(path) || Directory.Exists(path))
                    {
                        throw new IOException("BodyRig live quality receipt destination appeared before commit.");
                    }
                    File.Move(temporary, path);
                    temporary = null;
                }
                finally
                {
                    if (!string.IsNullOrEmpty(temporary) && File.Exists(temporary))
                    {
                        try { File.Delete(temporary); } catch (IOException) { } catch (UnauthorizedAccessException) { }
                    }
                }
                Debug.Log("BodyRig: live machine quality receipt committed: " + path + " pass=" + pass);
            }
            catch (Exception exc)
            {
                Debug.LogError("BodyRig: could not commit live machine quality receipt: " + exc.Message);
            }
        }

        private static string RequireEnvironment(string name)
        {
            var value = Environment.GetEnvironmentVariable(name);
            if (string.IsNullOrWhiteSpace(value))
            {
                throw new InvalidOperationException("BodyRig live quality environment is missing " + name + ".");
            }
            return value;
        }
    }
}
