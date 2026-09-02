using System;
using UnityEngine;

namespace ModelRig.BodyRig.UnityRenderer
{
    /// <summary>
    /// Small renderer-local fallback for semantic gestures when no authored
    /// Animator mapping exists. It deliberately supports only conservative
    /// proof gestures; richer person-specific motion comes from bodyprints later.
    /// </summary>
    public sealed class BodyRigProceduralGestureDriver : MonoBehaviour
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

        public void Apply(string intent, string state, long timestampMs, float energy)
        {
            if (!bound)
            {
                return;
            }
            if (state != "speaking" || intent != "explain")
            {
                Cancel();
                return;
            }

            var seconds = timestampMs / 1000.0f;
            var pulse = Mathf.Sin(seconds * Mathf.PI * 1.35f);
            var amplitude = Mathf.Lerp(0.55f, 1.0f, Mathf.Clamp01(energy));

            // Small mirrored offsets keep this safe across ordinary humanoid
            // VRM rigs while still making the body visibly participate.
            leftUpperArm.localRotation = leftUpperBase * Quaternion.Euler(
                -5.0f * amplitude,
                -2.0f * pulse,
                -10.0f * amplitude - 2.0f * pulse);
            rightUpperArm.localRotation = rightUpperBase * Quaternion.Euler(
                -5.0f * amplitude,
                2.0f * pulse,
                10.0f * amplitude + 2.0f * pulse);

            if (leftLowerArm != null)
            {
                leftLowerArm.localRotation = leftLowerBase * Quaternion.Euler(
                    -7.0f * amplitude,
                    0.0f,
                    -3.0f * pulse);
            }
            if (rightLowerArm != null)
            {
                rightLowerArm.localRotation = rightLowerBase * Quaternion.Euler(
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
