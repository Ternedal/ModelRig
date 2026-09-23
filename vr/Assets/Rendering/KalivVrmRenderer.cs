using System;
using UniVRM10;
using UnityEngine;

namespace Kaliv.VR.Rendering
{
    [DefaultExecutionOrder(11005)]
    public sealed class KalivVrmRenderer : MonoBehaviour
    {
        [SerializeField] private Transform defaultGazeTarget;
        [SerializeField] private KalivGestureRouter gestureRouter;
        [SerializeField] private KalivProceduralGestureDriver proceduralGestureDriver;
        [SerializeField, Range(0.0f, 30.0f)] private float maxGazeYawDegrees = 24.0f;
        [SerializeField, Range(0.0f, 20.0f)] private float maxGazePitchDegrees = 14.0f;
        [SerializeField, Range(0.0f, 12.0f)] private float proceduralHeadYawDegrees = 6.0f;
        [SerializeField, Range(0.0f, 8.0f)] private float proceduralHeadPitchDegrees = 4.0f;

        private Vrm10Instance avatar;
        private Animator animator;
        private Transform head;
        private Transform chest;
        private Transform leftEye;
        private Transform rightEye;
        private Quaternion headBaseLocalRotation;
        private Quaternion chestBaseLocalRotation;
        private Quaternion leftEyeBaseLocalRotation;
        private Quaternion rightEyeBaseLocalRotation;
        private KalivBodyRenderFrame currentFrame;
        private string activeGesture;
        private bool authoredMotionActive;
        private KalivSpatialTargetRegistry spatialTargets;

        private static readonly ExpressionPreset[] MouthPresets =
        {
            ExpressionPreset.aa,
            ExpressionPreset.ih,
            ExpressionPreset.ou,
            ExpressionPreset.ee,
            ExpressionPreset.oh,
        };

        private static readonly ExpressionPreset[] EmotionPresets =
        {
            ExpressionPreset.happy,
            ExpressionPreset.angry,
            ExpressionPreset.sad,
            ExpressionPreset.relaxed,
            ExpressionPreset.surprised,
        };

        public bool IsBound => avatar != null && animator != null;

        public void SetDefaultGazeTarget(Transform value)
        {
            defaultGazeTarget = value;
        }

        public void SetSpatialTargetRegistry(KalivSpatialTargetRegistry registry)
        {
            spatialTargets = registry;
        }

        public void SetAuthoredMotionActive(bool active)
        {
            authoredMotionActive = active;
            proceduralGestureDriver?.SetAuthoredMotionActive(active);
        }

        public void Bind(Vrm10Instance instance, Transform gazeTarget = null)
        {
            if (instance == null)
            {
                throw new ArgumentNullException(nameof(instance));
            }

            avatar = instance;
            animator = instance.GetComponent<Animator>();
            if (animator == null || !animator.isHuman)
            {
                throw new InvalidOperationException("Kaliv VR renderer requires a humanoid VRM Animator.");
            }

            defaultGazeTarget = gazeTarget != null ? gazeTarget : defaultGazeTarget;
            head = animator.GetBoneTransform(HumanBodyBones.Head);
            chest = animator.GetBoneTransform(HumanBodyBones.Chest);
            leftEye = animator.GetBoneTransform(HumanBodyBones.LeftEye);
            rightEye = animator.GetBoneTransform(HumanBodyBones.RightEye);

            if (head == null)
            {
                throw new InvalidOperationException("Kaliv VR renderer requires a humanoid head bone.");
            }

            headBaseLocalRotation = head.localRotation;
            if (chest != null)
            {
                chestBaseLocalRotation = chest.localRotation;
            }
            if (leftEye != null)
            {
                leftEyeBaseLocalRotation = leftEye.localRotation;
            }
            if (rightEye != null)
            {
                rightEyeBaseLocalRotation = rightEye.localRotation;
            }

            if (gestureRouter == null)
            {
                gestureRouter = GetComponent<KalivGestureRouter>();
            }
            if (gestureRouter == null)
            {
                gestureRouter = gameObject.AddComponent<KalivGestureRouter>();
            }
            gestureRouter.SetAnimator(animator);

            if (proceduralGestureDriver == null)
            {
                proceduralGestureDriver = GetComponent<KalivProceduralGestureDriver>();
            }
            if (proceduralGestureDriver == null)
            {
                proceduralGestureDriver = gameObject.AddComponent<KalivProceduralGestureDriver>();
            }
            proceduralGestureDriver.Bind(animator);
            proceduralGestureDriver.SetAuthoredMotionActive(authoredMotionActive);

            activeGesture = null;
            gestureRouter.Cancel();
            proceduralGestureDriver.Cancel();
            ClearFace();
        }

        public void ApplyJson(string json)
        {
            Apply(KalivBodyRenderFrame.Parse(json));
        }

        public void Apply(KalivBodyRenderFrame frame)
        {
            if (!IsBound)
            {
                throw new InvalidOperationException("Kaliv VR renderer is not bound to a VRM avatar.");
            }
            if (frame == null)
            {
                throw new ArgumentNullException(nameof(frame));
            }

            frame.Validate();
            currentFrame = frame;
            ApplyGesture(frame);
            ApplyFace(frame);
        }

        private void LateUpdate()
        {
            if (!IsBound || currentFrame == null)
            {
                return;
            }

            // UniVRM retargets VrmAnimation at execution order 11000.
            // Re-apply BodyRig face/head overlays afterwards so authored motion
            // cannot override speech, emotion, blink or gaze authority.
            ApplyFace(currentFrame);
            ApplyHeadAndGaze(currentFrame);
            ApplyBreath(currentFrame);
            proceduralGestureDriver.Apply(
                activeGesture,
                currentFrame.state,
                currentFrame.timestamp_ms,
                currentFrame.energy);
        }

        private void ApplyGesture(KalivBodyRenderFrame frame)
        {
            // BodyRig intentionally keeps the ModelRig semantic gesture in
            // frame.gesture and exposes any profile-selected source trajectory
            // separately as resolved_gesture (bodyprint:gesture-*). This renderer
            // has no trajectory decoder yet, so semantic gesture remains the only
            // safe routing authority; never reinterpret the replay id as an
            // Animator trigger or packaged VRMA filename.
            if (frame.state == "interrupted" || frame.state == "error")
            {
                activeGesture = null;
                gestureRouter.Cancel();
                proceduralGestureDriver.Cancel();
                return;
            }

            if (frame.gesture == activeGesture)
            {
                return;
            }

            activeGesture = frame.gesture;
            if (string.IsNullOrEmpty(activeGesture))
            {
                gestureRouter.Cancel();
                proceduralGestureDriver.Cancel();
            }
            else
            {
                gestureRouter.Route(activeGesture);
            }
        }

        private void ApplyFace(KalivBodyRenderFrame frame)
        {
            ClearFace();

            var blink = Mathf.Clamp01(frame.blink);
            SetPreset(ExpressionPreset.blink, blink);

            var interruptedOrSilent = frame.state != "speaking";
            if (!interruptedOrSilent)
            {
                if (frame.speech_timing_mode == "timed" && frame.visemes.Length > 0)
                {
                    foreach (var viseme in frame.visemes)
                    {
                        if (TryResolveViseme(viseme.id, out var preset))
                        {
                            SetPreset(preset, Mathf.Clamp01(viseme.weight));
                        }
                    }
                }
                else
                {
                    // Current VoiceRig RC25 has no phoneme timing. audio_envelope
                    // therefore controls a deliberately approximate open-mouth shape.
                    SetPreset(ExpressionPreset.aa, Mathf.Clamp01(frame.mouth_open));
                }
            }

            if (TryResolveEmotion(frame.emotion, out var emotionPreset))
            {
                SetPreset(emotionPreset, Mathf.Clamp01(frame.emotion_intensity));
            }
        }

        private void ApplyHeadAndGaze(KalivBodyRenderFrame frame)
        {
            var stateYaw = 0.0f;
            var statePitch = 0.0f;
            switch (frame.state)
            {
                case "listening":
                    statePitch = -2.0f;
                    break;
                case "thinking":
                    stateYaw = 5.0f;
                    statePitch = 1.5f;
                    break;
                case "interrupted":
                    statePitch = 1.0f;
                    break;
                case "error":
                    statePitch = 3.0f;
                    break;
            }

            var proceduralYaw = frame.head_yaw_hint * proceduralHeadYawDegrees;
            var proceduralPitch = frame.head_pitch_hint * proceduralHeadPitchDegrees;
            var gazeYaw = 0.0f;
            var gazePitch = 0.0f;

            var target = ResolveGazeTarget(frame.gaze_target);
            if (target != null && frame.gaze_strength > 0.0f)
            {
                var directionWorld = target.position - head.position;
                if (directionWorld.sqrMagnitude > 0.0001f)
                {
                    var directionLocal = avatar.transform.InverseTransformDirection(directionWorld.normalized);
                    var yaw = Mathf.Atan2(directionLocal.x, directionLocal.z) * Mathf.Rad2Deg;
                    var planar = Mathf.Sqrt(directionLocal.x * directionLocal.x + directionLocal.z * directionLocal.z);
                    var pitch = -Mathf.Atan2(directionLocal.y, planar) * Mathf.Rad2Deg;
                    gazeYaw = Mathf.Clamp(yaw, -maxGazeYawDegrees, maxGazeYawDegrees) * frame.gaze_strength;
                    gazePitch = Mathf.Clamp(pitch, -maxGazePitchDegrees, maxGazePitchDegrees) * frame.gaze_strength;
                }
            }

            var headMotionBase = authoredMotionActive ? head.localRotation : headBaseLocalRotation;
            head.localRotation = headMotionBase * Quaternion.Euler(
                statePitch + proceduralPitch + gazePitch * 0.45f,
                stateYaw + proceduralYaw + gazeYaw * 0.45f,
                0.0f);

            ApplyEyeRotation(leftEye, leftEyeBaseLocalRotation, gazeYaw, gazePitch);
            ApplyEyeRotation(rightEye, rightEyeBaseLocalRotation, gazeYaw, gazePitch);
        }

        private static void ApplyEyeRotation(
            Transform eye,
            Quaternion baseRotation,
            float gazeYaw,
            float gazePitch)
        {
            if (eye == null)
            {
                return;
            }

            eye.localRotation = baseRotation * Quaternion.Euler(
                gazePitch * 0.55f,
                gazeYaw * 0.55f,
                0.0f);
        }

        private void ApplyBreath(KalivBodyRenderFrame frame)
        {
            if (chest == null)
            {
                return;
            }

            var amplitude = 0.35f + 0.45f * frame.energy;
            var pitch = (frame.breath - 0.5f) * amplitude;
            var chestMotionBase = authoredMotionActive ? chest.localRotation : chestBaseLocalRotation;
            chest.localRotation = chestMotionBase * Quaternion.Euler(pitch, 0.0f, 0.0f);
        }

        private Transform ResolveGazeTarget(string target)
        {
            if (string.IsNullOrEmpty(target) || target == "none" || target == "away")
            {
                return null;
            }
            if (target == "user" || target == "camera")
            {
                if (defaultGazeTarget != null)
                {
                    return defaultGazeTarget;
                }
                return Camera.main != null ? Camera.main.transform : null;
            }

            if ((target.StartsWith("object:", StringComparison.Ordinal) ||
                 target.StartsWith("world:", StringComparison.Ordinal)) &&
                spatialTargets != null &&
                spatialTargets.TryResolve(target, out Transform spatialTarget))
            {
                return spatialTarget;
            }

            // Unknown semantic targets are presentation-local no-ops. Never guess.
            return null;
        }

        private void ClearFace()
        {
            if (avatar == null || avatar.Runtime == null)
            {
                return;
            }

            SetPreset(ExpressionPreset.blink, 0.0f);
            foreach (var preset in MouthPresets)
            {
                SetPreset(preset, 0.0f);
            }
            foreach (var preset in EmotionPresets)
            {
                SetPreset(preset, 0.0f);
            }
        }

        private void SetPreset(ExpressionPreset preset, float weight)
        {
            avatar.Runtime.Expression.SetWeight(
                ExpressionKey.CreateFromPreset(preset),
                Mathf.Clamp01(weight));
        }

        private static bool TryResolveViseme(string id, out ExpressionPreset preset)
        {
            switch ((id ?? string.Empty).ToLowerInvariant())
            {
                case "aa":
                case "a":
                    preset = ExpressionPreset.aa;
                    return true;
                case "ih":
                case "i":
                    preset = ExpressionPreset.ih;
                    return true;
                case "ou":
                case "u":
                    preset = ExpressionPreset.ou;
                    return true;
                case "ee":
                case "e":
                    preset = ExpressionPreset.ee;
                    return true;
                case "oh":
                case "o":
                    preset = ExpressionPreset.oh;
                    return true;
                default:
                    preset = ExpressionPreset.aa;
                    return false;
            }
        }

        private static bool TryResolveEmotion(string emotion, out ExpressionPreset preset)
        {
            switch ((emotion ?? string.Empty).ToLowerInvariant())
            {
                case "happy":
                case "joy":
                case "amused":
                case "excited":
                    preset = ExpressionPreset.happy;
                    return true;
                case "angry":
                case "annoyed":
                    preset = ExpressionPreset.angry;
                    return true;
                case "sad":
                case "concerned":
                    preset = ExpressionPreset.sad;
                    return true;
                case "relaxed":
                case "calm":
                    preset = ExpressionPreset.relaxed;
                    return true;
                case "surprised":
                    preset = ExpressionPreset.surprised;
                    return true;
                default:
                    preset = ExpressionPreset.neutral;
                    return false;
            }
        }
    }
}
