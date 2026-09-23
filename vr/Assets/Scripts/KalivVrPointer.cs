using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.InputSystem;
using UnityEngine.UI;
using UnityEngine.XR;
using Kaliv.VR.Rendering;
using CommonUsages = UnityEngine.XR.CommonUsages;

namespace Kaliv.VR
{
    /// <summary>Quest controller ray with gaze fallback for code-driven world-space UI.</summary>
    public sealed class KalivVrPointer : MonoBehaviour
    {
        private Camera _camera;
        private LineRenderer _laser;
        private GameObject _current;
        private bool _previousTrigger;
        private int _interactionMask;
        private InputAction _rightPos, _rightRot, _leftPos, _leftRot;

        public void Initialize(Camera camera)
        {
            _camera = camera;

            int uiLayer = LayerMask.NameToLayer(KalivVrComposition.UiLayerName);
            if (uiLayer < 0)
                throw new System.InvalidOperationException(
                    "Kaliv VR pointer requires the committed KalivUI layer.");
            _interactionMask = 1 << uiLayer;

            BuildLaser();
            BuildActions();
        }

        private void BuildLaser()
        {
            var go = new GameObject("KalivVR.PointerLaser");
            DontDestroyOnLoad(go);
            _laser = go.AddComponent<LineRenderer>();
            _laser.useWorldSpace = true;
            _laser.positionCount = 2;
            _laser.startWidth = 0.009f;
            _laser.endWidth = 0.003f;
            var shader = Shader.Find("Sprites/Default") ?? Shader.Find("UI/Default");
            if (shader == null)
            {
                Debug.LogError("[KalivVR] No supported pointer shader found.");
                _laser.enabled = false;
                return;
            }
            _laser.material = new Material(shader);
            ColorUtility.TryParseHtmlString("#D4AB52", out Color gold);
            _laser.startColor = new Color(gold.r, gold.g, gold.b, 0.95f);
            _laser.endColor = new Color(gold.r, gold.g, gold.b, 0.25f);
        }

        private void BuildActions()
        {
            _rightPos = Action("<XRController>{RightHand}/pointerPosition", "Vector3");
            _rightRot = Action("<XRController>{RightHand}/pointerRotation", "Quaternion");
            _leftPos = Action("<XRController>{LeftHand}/pointerPosition", "Vector3");
            _leftRot = Action("<XRController>{LeftHand}/pointerRotation", "Quaternion");
        }

        private static InputAction Action(string binding, string control)
        {
            var action = new InputAction(type: InputActionType.Value, expectedControlType: control);
            action.AddBinding(binding);
            action.Enable();
            return action;
        }

        private void Update()
        {
            if (_camera == null || EventSystem.current == null) return;

            bool controller = TryControllerRay(out Vector3 origin, out Vector3 direction);
            if (!controller)
            {
                origin = _camera.transform.position;
                direction = _camera.transform.forward;
            }

            GameObject target = null;
            Vector3 point = origin + direction * 3f;
            if (Physics.Raycast(
                    origin,
                    direction,
                    out RaycastHit hit,
                    8f,
                    _interactionMask,
                    QueryTriggerInteraction.Ignore))
            {
                point = hit.point;
                Transform t = hit.collider.transform;
                while (t != null)
                {
                    var selectable = t.GetComponent<Selectable>();
                    if (selectable != null && selectable.interactable)
                    {
                        target = selectable.gameObject;
                        break;
                    }
                    t = t.parent;
                }
            }

            _laser.SetPosition(0, origin);
            _laser.SetPosition(1, point);

            var eventData = new PointerEventData(EventSystem.current);
            if (target != _current)
            {
                if (_current != null)
                    ExecuteEvents.Execute(_current, eventData, ExecuteEvents.pointerExitHandler);
                _current = target;
                if (_current != null)
                    ExecuteEvents.Execute(_current, eventData, ExecuteEvents.pointerEnterHandler);
            }

            bool trigger = Pressed(XRNode.RightHand) || Pressed(XRNode.LeftHand);
            bool down = trigger && !_previousTrigger;
            _previousTrigger = trigger;

            if (!down || _current == null) return;

            var input = _current.GetComponent<InputField>() ?? _current.GetComponentInParent<InputField>();
            if (input != null && input.interactable)
            {
                EventSystem.current.SetSelectedGameObject(input.gameObject);
                input.ActivateInputField();
                return;
            }

            ExecuteEvents.Execute(_current, eventData, ExecuteEvents.pointerClickHandler);
        }

        private bool TryControllerRay(out Vector3 origin, out Vector3 direction)
        {
            bool useLeft = !Pressed(XRNode.RightHand) && Pressed(XRNode.LeftHand);
            if (TryActionRay(useLeft ? _leftPos : _rightPos, useLeft ? _leftRot : _rightRot,
                             out origin, out direction))
                return true;
            if (TryActionRay(useLeft ? _rightPos : _leftPos, useLeft ? _rightRot : _leftRot,
                             out origin, out direction))
                return true;

            foreach (var node in new[] { XRNode.RightHand, XRNode.LeftHand })
            {
                var device = InputDevices.GetDeviceAtXRNode(node);
                if (device.isValid &&
                    device.TryGetFeatureValue(CommonUsages.devicePosition, out origin) &&
                    device.TryGetFeatureValue(CommonUsages.deviceRotation, out Quaternion rot))
                {
                    direction = rot * Quaternion.Euler(45f, 0f, 0f) * Vector3.forward;
                    return true;
                }
            }

            origin = default;
            direction = default;
            return false;
        }

        private static bool TryActionRay(InputAction pos, InputAction rot,
                                         out Vector3 origin, out Vector3 direction)
        {
            origin = default;
            direction = default;
            if (pos == null || rot == null || pos.controls.Count == 0 || rot.controls.Count == 0)
                return false;

            Quaternion q = rot.ReadValue<Quaternion>();
            if (q == Quaternion.identity && pos.ReadValue<Vector3>() == Vector3.zero) return false;
            origin = pos.ReadValue<Vector3>();
            direction = q * Vector3.forward;
            return true;
        }

        private static bool Pressed(XRNode node)
        {
            var d = InputDevices.GetDeviceAtXRNode(node);
            return d.isValid &&
                   d.TryGetFeatureValue(CommonUsages.triggerButton, out bool pressed) &&
                   pressed;
        }

        private void OnDestroy()
        {
            _rightPos?.Dispose(); _rightRot?.Dispose();
            _leftPos?.Dispose(); _leftRot?.Dispose();
        }
    }
}
