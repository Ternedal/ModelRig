using System;
using System.Collections;
using System.Collections.Generic;
using System.Net;
using System.Net.Sockets;
using UnityEngine;
using UnityEngine.Networking;

namespace Kaliv.VR
{
    /// <summary>One rig found on the network.</summary>
    public sealed class KalivFoundRig
    {
        public string Url;
        public string Version;
    }

    /// <summary>
    /// Find the ModelRig backend on the local network, so the headset does not need a typed
    /// address that changes whenever the router hands the rig a new one.
    ///
    /// Client-only on purpose. ModelRig has no discovery protocol (Android pairs by QR, which a
    /// headset cannot scan), and adding a UDP responder like SkyPlayer's would mean a backend
    /// change and a new rig release before it worked. Instead the headset asks every address on
    /// its own subnet the question the backend already answers without authentication:
    /// GET /healthz → {"status":"ok","service":"modelrig-server","version":…}. Only that exact
    /// service name counts, so a printer or a router answering on 8080 is never mistaken for it.
    ///
    /// The scan is bounded: at most a /24 (254 addresses) per interface, a short timeout, a
    /// fixed number in flight. Nothing is sent but that one GET; no token leaves the headset.
    /// </summary>
    public static class KalivRigDiscovery
    {
        public const int DefaultPort = 8080;
        public const string ServiceName = "modelrig-server";
        private const int Parallel = 48;
        private const int TimeoutSeconds = 1;   // UnityWebRequest timeouts are whole seconds

        /// <summary>
        /// The addresses to probe for one interface: every host in its subnet, but never more
        /// than the /24 around the headset's own address — a /16 would be 65 534 requests.
        /// The headset itself, the network address and the broadcast address are skipped.
        /// </summary>
        public static List<string> ScanTargets(IPAddress self, IPAddress mask)
        {
            var result = new List<string>();
            if (self == null || self.AddressFamily != AddressFamily.InterNetwork) return result;
            byte[] ip = self.GetAddressBytes();
            byte[] m = mask != null && mask.AddressFamily == AddressFamily.InterNetwork
                ? mask.GetAddressBytes()
                : new byte[] { 255, 255, 255, 0 };

            uint ipU = ToUInt(ip), maskU = ToUInt(m);
            if (maskU < 0xFFFFFF00u) maskU = 0xFFFFFF00u;            // cap at /24
            if (maskU == 0xFFFFFFFFu || maskU == 0xFFFFFFFEu) return result;   // /32, /31: no neighbours

            uint network = ipU & maskU;
            uint broadcast = network | ~maskU;
            for (uint host = network + 1; host < broadcast; host++)
            {
                if (host == ipU) continue;
                result.Add(FromUInt(host).ToString());
            }
            return result;
        }

        /// <summary>True only for the backend's own health answer.</summary>
        public static bool IsModelRig(string body, out string version)
        {
            version = null;
            var o = KalivJson.TryParseObject(body);
            if (o == null || KalivJson.Str(o, "service") != ServiceName) return false;
            version = KalivJson.Str(o, "version");
            if (version.Length == 0) version = null;
            return true;
        }

        /// <summary>The headset's own IPv4 addresses with their masks (mask may be null).</summary>
        public static List<(IPAddress ip, IPAddress mask)> LocalInterfaces()
        {
            var list = new List<(IPAddress, IPAddress)>();
            try
            {
                foreach (var ni in System.Net.NetworkInformation.NetworkInterface.GetAllNetworkInterfaces())
                {
                    if (ni.OperationalStatus != System.Net.NetworkInformation.OperationalStatus.Up) continue;
                    foreach (var ua in ni.GetIPProperties().UnicastAddresses)
                    {
                        if (ua.Address.AddressFamily != AddressFamily.InterNetwork) continue;
                        if (IPAddress.IsLoopback(ua.Address)) continue;
                        IPAddress mask = null;
                        // Android's IL2CPP runtime does not always implement IPv4Mask; a /24
                        // is then assumed, which is what nearly every home network is.
                        try { mask = ua.IPv4Mask; } catch (Exception) { }
                        list.Add((ua.Address, mask));
                    }
                }
            }
            catch (Exception) { /* best effort: no interfaces means nothing to scan */ }
            return list;
        }

        /// <summary>
        /// Scan every local subnet. Reports progress (0..1) and each rig as it is found.
        /// <paramref name="extraPort"/> adds a second port when the user's saved address used one.
        /// </summary>
        public static IEnumerator Scan(int extraPort, Action<float> onProgress,
                                       Action<KalivFoundRig> onFound, Action<int> onDone,
                                       Func<bool> cancelled = null)
        {
            var targets = new List<string>();
            var seen = new HashSet<string>();
            var ports = new List<int> { DefaultPort };
            if (extraPort > 0 && extraPort != DefaultPort) ports.Add(extraPort);
            foreach (var (ip, mask) in LocalInterfaces())
                foreach (var host in ScanTargets(ip, mask))
                    foreach (int port in ports)
                    {
                        string url = $"http://{host}:{port}";
                        if (seen.Add(url)) targets.Add(url);
                    }

            int found = 0, done = 0;
            var running = new List<(UnityWebRequest req, string baseUrl)>();
            int next = 0;
            while (next < targets.Count || running.Count > 0)
            {
                if (cancelled != null && cancelled()) break;
                while (running.Count < Parallel && next < targets.Count)
                {
                    string baseUrl = targets[next++];
                    var req = UnityWebRequest.Get(baseUrl + "/healthz");
                    req.timeout = TimeoutSeconds;
                    req.redirectLimit = 0;
                    req.SendWebRequest();
                    running.Add((req, baseUrl));
                }
                for (int i = running.Count - 1; i >= 0; i--)
                {
                    var (req, baseUrl) = running[i];
                    if (!req.isDone) continue;
                    if (req.result == UnityWebRequest.Result.Success &&
                        IsModelRig(req.downloadHandler?.text, out string version))
                    {
                        found++;
                        onFound?.Invoke(new KalivFoundRig { Url = baseUrl, Version = version });
                    }
                    req.Dispose();
                    running.RemoveAt(i);
                    done++;
                }
                onProgress?.Invoke(targets.Count == 0 ? 1f : (float)done / targets.Count);
                yield return null;
            }
            foreach (var (req, _) in running) { req.Abort(); req.Dispose(); }
            onDone?.Invoke(found);
        }

        private static uint ToUInt(byte[] b) => ((uint)b[0] << 24) | ((uint)b[1] << 16) | ((uint)b[2] << 8) | b[3];

        private static IPAddress FromUInt(uint v) =>
            new IPAddress(new[] { (byte)(v >> 24), (byte)(v >> 16), (byte)(v >> 8), (byte)v });
    }
}
