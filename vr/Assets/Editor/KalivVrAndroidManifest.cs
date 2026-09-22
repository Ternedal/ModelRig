#if UNITY_ANDROID
using System.IO;
using System.Xml;
using UnityEditor.Android;
using UnityEngine;

namespace Kaliv.VR.EditorTools
{
    /// <summary>
    /// ModelRig commonly runs over plain HTTP on a trusted LAN/Tailscale path.
    /// Unity and Android each have their own cleartext gate, so the player setting
    /// and generated manifest must both allow it.
    /// </summary>
    public sealed class KalivVrAndroidManifest : IPostGenerateGradleAndroidProject
    {
        public int callbackOrder => 100;

        public void OnPostGenerateGradleAndroidProject(string path)
        {
            string manifestPath = Path.Combine(path, "src", "main", "AndroidManifest.xml");
            if (!File.Exists(manifestPath)) return;

            const string androidNs = "http://schemas.android.com/apk/res/android";
            var doc = new XmlDocument();
            doc.Load(manifestPath);

            var ns = new XmlNamespaceManager(doc.NameTable);
            ns.AddNamespace("android", androidNs);

            if (doc.SelectSingleNode("/manifest/application", ns) is XmlElement app)
                app.SetAttribute("usesCleartextTraffic", androidNs, "true");

            if (doc.SelectSingleNode("/manifest", ns) is XmlElement root)
            {
                bool hasInternet = false;
                foreach (XmlNode node in doc.SelectNodes("/manifest/uses-permission", ns))
                {
                    if (node is XmlElement permission &&
                        permission.GetAttribute("name", androidNs) == "android.permission.INTERNET")
                    {
                        hasInternet = true;
                        break;
                    }
                }

                if (!hasInternet)
                {
                    var permission = doc.CreateElement("uses-permission");
                    permission.SetAttribute("name", androidNs, "android.permission.INTERNET");
                    root.PrependChild(permission);
                }

                bool hasPassthrough = false;
                foreach (XmlNode node in doc.SelectNodes("/manifest/uses-feature", ns))
                {
                    if (node is XmlElement feature &&
                        feature.GetAttribute("name", androidNs) == "com.oculus.feature.PASSTHROUGH")
                    {
                        hasPassthrough = true;
                        break;
                    }
                }

                if (!hasPassthrough)
                {
                    var feature = doc.CreateElement("uses-feature");
                    feature.SetAttribute("name", androidNs, "com.oculus.feature.PASSTHROUGH");
                    feature.SetAttribute("required", androidNs, "false");
                    root.AppendChild(feature);
                }
            }

            doc.Save(manifestPath);
            Debug.Log("[KalivVR] Android manifest: INTERNET + cleartext + optional passthrough verified.");
        }
    }
}
#endif
