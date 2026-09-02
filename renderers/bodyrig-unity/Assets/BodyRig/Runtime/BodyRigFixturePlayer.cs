using System;
using UnityEngine;

namespace ModelRig.BodyRig.UnityRenderer
{
    public sealed class BodyRigFixturePlayer : MonoBehaviour
    {
        [SerializeField] private BodyRigVrmRenderer renderer;
        [SerializeField] private string resourceName = "bodyrig-demo";
        [SerializeField] private bool loop = true;
        [SerializeField, Min(0.05f)] private float playbackRate = 1.0f;
        [SerializeField, Min(100)] private int loopHoldMs = 800;

        private BodyRigRenderFrameSequence sequence;
        private float startedAt;
        private int index;
        private long durationMs;
        private bool playbackStarted;

        public BodyRigVrmRenderer Renderer
        {
            get => renderer;
            set => renderer = value;
        }

        public string ResourceName
        {
            get => resourceName;
            set => resourceName = value;
        }

        private void Start()
        {
            var fixture = Resources.Load<TextAsset>(resourceName);
            if (fixture == null)
            {
                Debug.LogWarning("BodyRig: demo fixture not found in Resources: " + resourceName);
                enabled = false;
                return;
            }

            try
            {
                sequence = JsonUtility.FromJson<BodyRigRenderFrameSequence>(fixture.text);
                if (sequence == null || sequence.frames == null || sequence.frames.Length == 0)
                {
                    throw new FormatException("BodyRig fixture must contain at least one frame.");
                }

                long previous = -1;
                foreach (var frame in sequence.frames)
                {
                    if (frame == null)
                    {
                        throw new FormatException("BodyRig fixture contains a null frame.");
                    }
                    frame.Validate();
                    if (frame.timestamp_ms <= previous)
                    {
                        throw new FormatException("BodyRig fixture timestamps must be strictly increasing.");
                    }
                    previous = frame.timestamp_ms;
                }

                // Keep the final fixture pose visible before rewinding. Without
                // this hold the modulo boundary would make the final frame
                // unreachable in looping playback.
                durationMs = sequence.frames[sequence.frames.Length - 1].timestamp_ms + loopHoldMs;
            }
            catch (Exception exc)
            {
                Debug.LogError("BodyRig: demo fixture rejected: " + exc);
                enabled = false;
                return;
            }

            index = 0;
            playbackStarted = false;
        }

        private void Update()
        {
            if (renderer == null || sequence == null || sequence.frames == null || sequence.frames.Length == 0)
            {
                return;
            }

            // VRM loading is asynchronous. Do not consume fixture frames while
            // there is no avatar to receive them; start the deterministic clock
            // only after the renderer is actually bound.
            if (!renderer.IsBound)
            {
                index = 0;
                playbackStarted = false;
                return;
            }

            if (!playbackStarted)
            {
                startedAt = Time.unscaledTime;
                index = 0;
                playbackStarted = true;
            }

            var elapsedMs = (long)((Time.unscaledTime - startedAt) * 1000.0f * playbackRate);
            if (loop && durationMs > 0)
            {
                elapsedMs %= durationMs;
                if (index > 0 && elapsedMs < sequence.frames[index - 1].timestamp_ms)
                {
                    index = 0;
                }
            }

            while (index < sequence.frames.Length && sequence.frames[index].timestamp_ms <= elapsedMs)
            {
                renderer.Apply(sequence.frames[index]);
                index++;
            }

            if (!loop && index >= sequence.frames.Length)
            {
                enabled = false;
            }
        }
    }
}
