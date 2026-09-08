// Slice D, the AR half: put the loaded avatar in the room.
//
// Compiled only when BODYRIG_AR is defined. AR Foundation/ARCore are Android
// build dependencies, not dependencies of the physically proven Windows path.
//
// This component never owns the controller GameObject. BodyRigVrmLoader binds
// the actual loaded VRM transform after renderer binding; only that child is
// hidden/moved. Keeping the controller root active means placement can still
// receive a tap while the avatar itself is hidden.
#if BODYRIG_AR
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.XR.ARFoundation;
using UnityEngine.XR.ARSubsystems;

namespace ModelRig.BodyRig.UnityRenderer
{
    public sealed class BodyRigArPlacement : MonoBehaviour
    {
        [SerializeField] private BodyRigVrmLoader loader;
        [SerializeField] private ARRaycastManager raycastManager;
        [SerializeField] private float faceCameraYawOnly = 1.0f;

        private static readonly List<ARRaycastHit> Hits = new List<ARRaycastHit>();
        private Transform avatarRoot;
        private Pose pendingPose;
        private bool hasPendingPose;
        private bool placed;

        public BodyRigVrmLoader Loader
        {
            get => loader;
            set => loader = value;
        }

        public ARRaycastManager RaycastManager
        {
            get => raycastManager;
            set => raycastManager = value;
        }

        public bool IsPlaced => placed;

        private void Start()
        {
            if (loader == null)
            {
                loader = GetComponent<BodyRigVrmLoader>();
            }
            if (raycastManager == null)
            {
                raycastManager = FindFirstObjectByType<ARRaycastManager>();
            }
            if (loader == null || raycastManager == null)
            {
                Debug.LogWarning(
                    "BodyRig: AR placement needs BodyRigVrmLoader and ARRaycastManager; avatar stays hidden.");
                enabled = false;
            }
        }

        /// <summary>
        /// Called by BodyRigVrmLoader only after the VRM has bound successfully.
        /// Hides the avatar child, never the controller root. If the user already
        /// tapped a plane while loading, that queued pose is applied immediately.
        /// </summary>
        public void BindAvatarRoot(Transform loadedAvatarRoot)
        {
            if (loadedAvatarRoot == null)
            {
                return;
            }
            avatarRoot = loadedAvatarRoot;
            avatarRoot.gameObject.SetActive(false);
            placed = false;

            if (hasPendingPose)
            {
                var pose = pendingPose;
                hasPendingPose = false;
                PlaceLoadedAvatar(pose);
            }
        }

        private void Update()
        {
            if (raycastManager == null || Input.touchCount == 0)
            {
                return;
            }
            var touch = Input.GetTouch(0);
            if (touch.phase != TouchPhase.Began)
            {
                return;
            }
            if (!raycastManager.Raycast(touch.position, Hits, TrackableType.PlaneWithinPolygon))
            {
                return;
            }
            Place(Hits[0].pose);
        }

        /// <summary>
        /// Stand the avatar on a plane pose, facing the camera (yaw only). A tap
        /// that arrives before async VRM load completes is retained, not guessed.
        /// </summary>
        public void Place(Pose pose)
        {
            if (avatarRoot == null)
            {
                pendingPose = pose;
                hasPendingPose = true;
                return;
            }
            PlaceLoadedAvatar(pose);
        }

        private void PlaceLoadedAvatar(Pose pose)
        {
            avatarRoot.SetPositionAndRotation(pose.position, pose.rotation);
            var camera = Camera.main;
            if (camera != null && faceCameraYawOnly > 0.0f)
            {
                var toCamera = camera.transform.position - avatarRoot.position;
                toCamera.y = 0.0f;
                if (toCamera.sqrMagnitude > 0.0001f)
                {
                    avatarRoot.rotation = Quaternion.LookRotation(toCamera.normalized, Vector3.up);
                }
            }
            avatarRoot.gameObject.SetActive(true);
            placed = true;
        }
    }
}
#endif
