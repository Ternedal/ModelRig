using System;
using UnityEngine;

namespace Kaliv.VR.Rendering
{
    [Serializable]
    public sealed class KalivGestureBinding
    {
        public string intent;
        public string animatorTrigger;
        public string cancelTrigger;
        public string neutralState;
    }

    public sealed class KalivGestureRouter : MonoBehaviour
    {
        [SerializeField] private Animator animator;
        [SerializeField] private KalivGestureBinding[] bindings = Array.Empty<KalivGestureBinding>();
        [SerializeField, Range(0.0f, 0.5f)] private float neutralCrossFadeSeconds = 0.08f;

        private string activeIntent;

        public event Action<string> GestureRequested;
        public event Action<string> GestureCancelled;

        public string ActiveIntent => activeIntent;

        public void Route(string intent)
        {
            if (string.IsNullOrEmpty(intent))
            {
                Cancel();
                return;
            }
            if (intent == activeIntent)
            {
                return;
            }

            Cancel();
            activeIntent = intent;
            GestureRequested?.Invoke(intent);

            var binding = FindBinding(intent);
            if (animator == null || binding == null || string.IsNullOrEmpty(binding.animatorTrigger))
            {
                return;
            }

            animator.SetTrigger(binding.animatorTrigger);
        }

        public void Cancel()
        {
            if (string.IsNullOrEmpty(activeIntent))
            {
                return;
            }

            var cancelled = activeIntent;
            var binding = FindBinding(cancelled);
            activeIntent = null;

            if (animator != null && binding != null)
            {
                if (!string.IsNullOrEmpty(binding.animatorTrigger))
                {
                    animator.ResetTrigger(binding.animatorTrigger);
                }
                if (!string.IsNullOrEmpty(binding.cancelTrigger))
                {
                    animator.SetTrigger(binding.cancelTrigger);
                }
                else if (!string.IsNullOrEmpty(binding.neutralState))
                {
                    animator.CrossFadeInFixedTime(binding.neutralState, neutralCrossFadeSeconds);
                }
            }

            GestureCancelled?.Invoke(cancelled);
        }

        public void SetAnimator(Animator value)
        {
            if (animator != value)
            {
                Cancel();
                animator = value;
            }
        }

        private KalivGestureBinding FindBinding(string intent)
        {
            if (bindings == null)
            {
                return null;
            }

            foreach (var binding in bindings)
            {
                if (binding != null && binding.intent == intent)
                {
                    return binding;
                }
            }
            return null;
        }
    }
}
