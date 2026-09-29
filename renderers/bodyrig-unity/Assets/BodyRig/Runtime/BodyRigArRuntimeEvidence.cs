#if BODYRIG_AR
using UnityEngine;
using UnityEngine.XR.ARFoundation;

namespace ModelRig.BodyRig.UnityRenderer
{
    /// <summary>
    /// Emits bounded, non-secret AR session state markers for physical
    /// qualification. It carries no release or production authority itself.
    /// </summary>
    public sealed class BodyRigArRuntimeEvidence : MonoBehaviour
    {
        private void OnEnable()
        {
            ARSession.stateChanged += OnStateChanged;
            Emit(ARSession.state);
        }

        private void OnDisable()
        {
            ARSession.stateChanged -= OnStateChanged;
        }

        private static void OnStateChanged(ARSessionStateChangedEventArgs args)
        {
            Emit(args.state);
        }

        private static void Emit(ARSessionState state)
        {
            switch (state)
            {
                case ARSessionState.Unsupported:
                    Debug.LogWarning("BodyRig: AR session unsupported.");
                    break;
                case ARSessionState.NeedsInstall:
                    Debug.LogWarning("BodyRig: AR session needs install.");
                    break;
                case ARSessionState.Installing:
                    Debug.Log("BodyRig: AR session installing.");
                    break;
                case ARSessionState.Ready:
                    Debug.Log("BodyRig: AR session ready.");
                    break;
                case ARSessionState.SessionInitializing:
                    Debug.Log("BodyRig: AR session initializing.");
                    break;
                case ARSessionState.SessionTracking:
                    Debug.Log("BodyRig: AR session tracking.");
                    break;
            }
        }
    }
}
#endif
