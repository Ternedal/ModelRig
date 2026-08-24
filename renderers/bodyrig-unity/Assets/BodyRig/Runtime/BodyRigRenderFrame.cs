using System;
using System.Collections.Generic;
using UnityEngine;

namespace ModelRig.BodyRig.UnityRenderer
{
    [Serializable]
    public sealed class BodyRigVisemeWeight
    {
        public string id;
        public float weight;
    }

    [Serializable]
    public sealed class BodyRigFaceChannel
    {
        public string id;
        public float value;
    }

    [Serializable]
    public sealed class BodyRigFaceChannelSource
    {
        public string id;
        public string source;
    }

    [Serializable]
    public sealed class BodyRigOptionalFrequency
    {
        public bool present;
        public float value;
    }

    [Serializable]
    public sealed class BodyRigRenderFrame
    {
        public string type;
        public string version;
        public long timestamp_ms;
        public string state;
        public string gesture;
        public string gaze_target;
        public float gaze_strength;
        public string emotion;
        public float emotion_intensity;
        public float energy;
        public float mouth_open;
        public BodyRigVisemeWeight[] visemes;
        public string speech_timing_mode;
        public float blink;
        public float breath;
        public float head_yaw_hint;
        public float head_pitch_hint;

        // M2.2 renderer-neutral face personalization. These are BodyRig semantic
        // channels; VRM ExpressionPreset mapping remains renderer-local.
        public string face_profile_id;
        public BodyRigFaceChannel[] face_channels;
        public BodyRigFaceChannelSource[] face_channel_sources;

        // M2.3 renderer-neutral body-motion personalization. The current proof
        // retains every field even when it does not yet render every hint.
        public string body_motion_profile_id;
        public string body_motion_source;
        public float head_motion_scale;
        public float micro_motion_scale;
        public float posture_lean_x;
        public string posture_source;
        public string resolved_gesture;
        public string gesture_resolution_source;
        public string dominant_side_hint;
        public BodyRigOptionalFrequency gesture_frequency_per_minute;

        private static readonly HashSet<string> States = new HashSet<string>
        {
            "idle",
            "listening",
            "thinking",
            "speaking",
            "waiting_for_tool",
            "interrupted",
            "error",
        };

        private static readonly HashSet<string> BodyMotionSources = new HashSet<string>
        {
            "generic",
            "profile",
        };

        private static readonly HashSet<string> GestureResolutionSources = new HashSet<string>
        {
            "none",
            "semantic",
            "explicit_profile",
            "profile_replay",
        };

        private static readonly HashSet<string> DominantSides = new HashSet<string>
        {
            "left",
            "right",
            "balanced",
        };

        public static BodyRigRenderFrame Parse(string json)
        {
            if (string.IsNullOrWhiteSpace(json))
            {
                throw new ArgumentException("BodyRig render frame JSON is required.", nameof(json));
            }

            BodyRigRenderFrame frame;
            try
            {
                frame = JsonUtility.FromJson<BodyRigRenderFrame>(json);
            }
            catch (Exception exc)
            {
                throw new FormatException("BodyRig render frame JSON is malformed.", exc);
            }

            if (frame == null)
            {
                throw new FormatException("BodyRig render frame JSON did not produce an object.");
            }

            frame.Validate();
            return frame;
        }

        public void Validate()
        {
            if (type != "bodyrig.render_frame" || version != "0.1")
            {
                throw new FormatException("Unsupported BodyRig render frame type/version.");
            }
            if (timestamp_ms < 0)
            {
                throw new FormatException("timestamp_ms must be non-negative.");
            }
            if (string.IsNullOrEmpty(state) || !States.Contains(state))
            {
                throw new FormatException("Unsupported BodyRig state.");
            }
            if (string.IsNullOrEmpty(emotion))
            {
                throw new FormatException("emotion must be a non-empty string.");
            }
            if (visemes == null)
            {
                throw new FormatException("visemes must be present, even when empty.");
            }
            if (face_channels == null || face_channel_sources == null)
            {
                throw new FormatException("face channels and sources must both be present.");
            }
            if (face_channels.Length != face_channel_sources.Length)
            {
                throw new FormatException("face channel/source counts must match.");
            }
            if (gesture_frequency_per_minute == null)
            {
                throw new FormatException("gesture_frequency_per_minute must be present.");
            }

            Unit(gaze_strength, nameof(gaze_strength));
            Unit(emotion_intensity, nameof(emotion_intensity));
            Unit(energy, nameof(energy));
            Unit(mouth_open, nameof(mouth_open));
            Unit(blink, nameof(blink));
            Unit(breath, nameof(breath));
            Hint(head_yaw_hint, nameof(head_yaw_hint));
            Hint(head_pitch_hint, nameof(head_pitch_hint));
            Range(head_motion_scale, 0.0f, 2.0f, nameof(head_motion_scale));
            Range(micro_motion_scale, 0.0f, 2.0f, nameof(micro_motion_scale));
            Hint(posture_lean_x, nameof(posture_lean_x));

            var visemeIds = new HashSet<string>();
            foreach (var viseme in visemes)
            {
                if (viseme == null || string.IsNullOrEmpty(viseme.id))
                {
                    throw new FormatException("Each BodyRig viseme requires a non-empty id.");
                }
                if (!visemeIds.Add(viseme.id))
                {
                    throw new FormatException("BodyRig viseme ids must be unique.");
                }
                Unit(viseme.weight, "viseme.weight");
            }

            if (!string.IsNullOrEmpty(speech_timing_mode)
                && speech_timing_mode != "audio_envelope"
                && speech_timing_mode != "timed")
            {
                throw new FormatException("Unsupported speech_timing_mode.");
            }

            var faceIds = new HashSet<string>();
            for (var index = 0; index < face_channels.Length; index++)
            {
                var channel = face_channels[index];
                var source = face_channel_sources[index];
                if (channel == null || string.IsNullOrEmpty(channel.id))
                {
                    throw new FormatException("Each face channel requires a non-empty id.");
                }
                if (source == null || source.id != channel.id || string.IsNullOrEmpty(source.source))
                {
                    throw new FormatException("Face channel source ids/order must match channel ids/order.");
                }
                if (!faceIds.Add(channel.id))
                {
                    throw new FormatException("Face channel ids must be unique.");
                }
                Unit(channel.value, "face_channel.value");
            }

            if (!BodyMotionSources.Contains(body_motion_source))
            {
                throw new FormatException("Unsupported body_motion_source.");
            }
            if (!BodyMotionSources.Contains(posture_source))
            {
                throw new FormatException("Unsupported posture_source.");
            }
            if (!GestureResolutionSources.Contains(gesture_resolution_source))
            {
                throw new FormatException("Unsupported gesture_resolution_source.");
            }
            if (!string.IsNullOrEmpty(dominant_side_hint) && !DominantSides.Contains(dominant_side_hint))
            {
                throw new FormatException("Unsupported dominant_side_hint.");
            }

            Range(
                gesture_frequency_per_minute.value,
                0.0f,
                600.0f,
                "gesture_frequency_per_minute.value");
            if (!gesture_frequency_per_minute.present && gesture_frequency_per_minute.value != 0.0f)
            {
                throw new FormatException(
                    "Absent gesture_frequency_per_minute must carry canonical zero value.");
            }
        }

        private static void Unit(float value, string field)
        {
            Range(value, 0.0f, 1.0f, field);
        }

        private static void Hint(float value, string field)
        {
            Range(value, -1.0f, 1.0f, field);
        }

        private static void Range(float value, float minimum, float maximum, string field)
        {
            if (float.IsNaN(value) || float.IsInfinity(value) || value < minimum || value > maximum)
            {
                throw new FormatException(field + " is out of range.");
            }
        }
    }

    [Serializable]
    public sealed class BodyRigRenderFrameSequence
    {
        public BodyRigRenderFrame[] frames;
    }
}
