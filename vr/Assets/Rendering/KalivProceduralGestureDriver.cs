using System;
using UnityEngine;

namespace Kaliv.VR.Rendering
{
    /// <summary>
    /// Small renderer-local fallback for semantic gestures when no authored
    /// Animator mapping exists. It deliberately supports only conservative
    /// proof gestures; richer person-specific motion comes from bodyprints later.
    /// </summary>
    public sealed class KalivProceduralGestureDriver : MonoBehaviour
    {
        private Transform leftUpperArm;
        private Transform rightUpperArm;
        private Transform leftLowerArm;
        private Transform rightLowerArm;
        private Quaternion leftUpperBase;
        private Quaternion rightUpperBase;
        private Quaternion leftLowerBase;
        private Quaternion rightLowerBase;
        private bool bound;
        private bool authoredMotionActive;

        public void Bind(Animator animator)
        {
            if (animator == null || !animator.isHuman)
            {
                throw new ArgumentException("A humanoid Animator is required.", nameof(animator));
            }

            leftUpperArm = animator.GetBoneTransform(HumanBodyBones.LeftUpperArm);
            rightUpperArm = animator.GetBoneTransform(HumanBodyBones.RightUpperArm);
            leftLowerArm = animator.GetBoneTransform(HumanBodyBones.LeftLowerArm);
            rightLowerArm = animator.GetBoneTransform(HumanBodyBones.RightLowerArm);

            if (leftUpperArm == null || rightUpperArm == null)
            {
                throw new InvalidOperationException("Procedural gesture fallback requires both upper-arm bones.");
            }

            leftUpperBase = leftUpperArm.localRotation;
            rightUpperBase = rightUpperArm.localRotation;
            if (leftLowerArm != null)
            {
                leftLowerBase = leftLowerArm.localRotation;
            }
            if (rightLowerArm != null)
            {
                rightLowerBase = rightLowerArm.localRotation;
            }
            bound = true;
            Cancel();
        }

        public void SetAuthoredMotionActive(bool active)
        {
            authoredMotionActive = active;
        }

        public void Apply(string intent, string state, long timestampMs, float energy)
        {
            if (!bound)
            {
                return;
            }
            if (state != "speaking" || intent != "explain")
            {
                if (!authoredMotionActive) Cancel();
                return;
            }

            var seconds = timestampMs / 1000.0f;
            var pulse = Mathf.Sin(seconds * Mathf.PI * 1.35f);
            var amplitude = Mathf.Lerp(0.55f, 1.0f, Mathf.Clamp01(energy));

            // Small mirrored offsets keep this safe across ordinary humanoid
            // VRM rigs while still making the body visibly participate.
            var leftUpperMotionBase = authoredMotionActive ? leftUpperArm.localRotation : leftUpperBase;
            var rightUpperMotionBase = authoredMotionActive ? rightUpperArm.localRotation : rightUpperBase;
            leftUpperArm.localRotation = leftUpperMotionBase * Quaternion.Euler(
                -5.0f * amplitude,
                -2.0f * pulse,
                -10.0f * amplitude - 2.0f * pulse);
            rightUpperArm.localRotation = rightUpperMotionBase * Quaternion.Euler(
                -5.0f * amplitude,
                2.0f * pulse,
                10.0f * amplitude + 2.0f * pulse);

            if (leftLowerArm != null)
            {
                var leftLowerMotionBase = authoredMotionActive ? leftLowerArm.localRotation : leftLowerBase;
                leftLowerArm.localRotation = leftLowerMotionBase * Quaternion.Euler(
                    -7.0f * amplitude,
                    0.0f,
                    -3.0f * pulse);
            }
            if (rightLowerArm != null)
            {
                var rightLowerMotionBase = authoredMotionActive ? rightLowerArm.localRotation : rightLowerBase;
                rightLowerArm.localRotation = rightLowerMotionBase * Quaternion.Euler(
                    -7.0f * amplitude,
                    0.0f,
                    3.0f * pulse);
            }
        }

        public void Cancel()
        {
            if (!bound)
            {
                return;
            }

            if (authoredMotionActive) return;

            leftUpperArm.localRotation = leftUpperBase;
            rightUpperArm.localRotation = rightUpperBase;
            if (leftLowerArm != null)
            {
                leftLowerArm.localRotation = leftLowerBase;
            }
            if (rightLowerArm != null)
            {
                rightLowerArm.localRotation = rightLowerBase;
            }
        }
    }
}
