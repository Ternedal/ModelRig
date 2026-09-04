// Slice D, the AR half: put the body in the room.
//
// Compiled only when BODYRIG_AR is defined. That define is set by the
// operator after installing AR Foundation and the ARCore XR plugin from the
// Package Manager (see README, "Android + AR"). Without it this file is
// empty, so the Windows proof and the fixture path build exactly as before
// and no package version is pinned blind.
//
// The component moves ONE transform -- the avatar root -- onto a detected
// plane where the user taps, and keeps it there. It never touches bones,
// expressions or frames: the renderer keeps applying the rig's frames to
// the same avatar, which now happens to stand on the floor in front of the
// camera. AR session, XR origin, plane and raycast managers come from the
// scene (Unity's "XR Origin (AR)" prefab); this only asks the raycast
// manager where the floor is.
#if BODYRIG_AR
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.XR.ARFoundation;
using UnityEngine.XR.ARSubsystems;

namespace ModelRig.BodyRig.UnityRenderer
{
    public sealed class BodyRigArPlacement : MonoBehaviour
    {
        [SerializeField] private Transform avatarRoot;
        [SerializeField] private ARRaycastManager raycastManager;
        [SerializeField] private float faceCameraYawOnly = 1.0f;

        private static readonly List<ARRaycastHit> Hits = new List<ARRaycastHit>();
        private bool placed;

        public Transform AvatarRoot
        {
            get => avatarRoot;
            set => avatarRoot = value;
        }

        public ARRaycastManager RaycastManager
        {
            get => raycastManager;
            set => raycastManager = value;
        }

        public bool IsPlaced => placed;

        private void Start()
        {
            if (raycastManager == null)
            {
                raycastManager = FindFirstObjectByType<ARRaycastManager>();
            }
            if (avatarRoot == null || raycastManager == null)
            {
                Debug.LogWarning("BodyRig: AR placement needs an avatar root and an ARRaycastManager in the scene.");
                enabled = false;
                return;
            }
            // Hidden until the user has chosen a spot: a body floating at the
            // origin before any plane exists is not "in the room".
            avatarRoot.gameObject.SetActive(false);
        }

        private void Update()
        {
            if (Input.touchCount == 0)
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

        /// <summary>Stand the avatar on the hit pose, facing the camera (yaw only).</summary>
        public void Place(Pose pose)
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
