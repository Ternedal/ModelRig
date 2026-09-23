using System;
using System.Collections.Generic;
using UnityEngine;

namespace Kaliv.VR.Rendering
{
    /// <summary>
    /// Renderer-local mapping from BodyRig semantic spatial tokens to scene transforms.
    ///
    /// The wire remains renderer-neutral: BodyRig may say "object:screen" or
    /// "world:door", while only Kaliv VR knows which Transform currently represents it.
    /// Unknown targets are a local no-op, never guessed.
    /// </summary>
    public sealed class KalivSpatialTargetRegistry : MonoBehaviour
    {
        private readonly Dictionary<string, Transform> _targets =
            new Dictionary<string, Transform>(StringComparer.Ordinal);

        public int Count => _targets.Count;

        public void RegisterObject(string id, Transform target) =>
            Register("object:" + ValidateId(id), target);

        public void RegisterWorld(string id, Transform target) =>
            Register("world:" + ValidateId(id), target);

        public void Register(string semanticTarget, Transform target)
        {
            if (target == null) throw new ArgumentNullException(nameof(target));
            string key = ValidateSemanticTarget(semanticTarget);
            _targets[key] = target;
        }

        public bool Unregister(string semanticTarget)
        {
            string key = ValidateSemanticTarget(semanticTarget);
            return _targets.Remove(key);
        }

        public bool TryResolve(string semanticTarget, out Transform target)
        {
            target = null;
            if (!TryValidateSemanticTarget(semanticTarget, out string key))
                return false;

            if (!_targets.TryGetValue(key, out target) || target == null)
            {
                _targets.Remove(key);
                target = null;
                return false;
            }
            return true;
        }

        public void Clear() => _targets.Clear();

        private static string ValidateSemanticTarget(string value)
        {
            if (!TryValidateSemanticTarget(value, out string normalized))
                throw new ArgumentException(
                    "Spatial target must be object:<id> or world:<id> using a safe local id.",
                    nameof(value));
            return normalized;
        }

        private static bool TryValidateSemanticTarget(string value, out string normalized)
        {
            normalized = null;
            value = (value ?? "").Trim();
            string prefix;
            if (value.StartsWith("object:", StringComparison.Ordinal))
                prefix = "object:";
            else if (value.StartsWith("world:", StringComparison.Ordinal))
                prefix = "world:";
            else
                return false;

            string id = value.Substring(prefix.Length);
            if (!TryValidateId(id)) return false;

            normalized = prefix + id;
            return normalized.Length <= 160;
        }

        private static string ValidateId(string id)
        {
            id = (id ?? "").Trim();
            if (!TryValidateId(id))
                throw new ArgumentException(
                    "Spatial target id must contain only letters, digits, '.', '_' or '-'.",
                    nameof(id));
            return id;
        }

        private static bool TryValidateId(string id)
        {
            if (string.IsNullOrWhiteSpace(id) || id.Length > 153) return false;
            foreach (char c in id)
            {
                if (!char.IsLetterOrDigit(c) && c != '.' && c != '_' && c != '-')
                    return false;
            }
            return true;
        }
    }
}
