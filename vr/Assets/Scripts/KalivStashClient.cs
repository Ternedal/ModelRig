using System;
using System.Collections;
using System.Collections.Generic;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using UnityEngine;
using UnityEngine.Networking;

namespace Kaliv.VR
{
    /// <summary>
    /// Talks to the SkyPlayer companion on the Stash server. No token: the companion is a LAN
    /// service with no pairing, so nothing from the rig's pairing is ever sent to it.
    /// </summary>
    public sealed class KalivStashClient : MonoBehaviour
    {
        private const int TimeoutSeconds = 10;

        public string BaseUrl { get; set; } = "";

        public IEnumerator Scenes(KalivStashOrder order, string query, string studioId, string tagId, int page,
                                  string seed, Action<KalivStashPage> ok, Action<string> fail)
        {
            yield return Get(KalivStash.ScenesUrl(BaseUrl, order, query, studioId, tagId, page, seed),
                text => ok?.Invoke(KalivStash.ParseScenes(text)), fail);
        }

        /// <summary>ROULETTE. A 404 means "nothing matches" — or an old companion without the route.</summary>
        public IEnumerator Random(string query, string studioId, string tagId,
                                  Action<KalivStashScene> ok, Action<string> fail)
        {
            yield return Get(KalivStash.RandomUrl(BaseUrl, query, studioId, tagId),
                text =>
                {
                    var s = KalivStash.ParseRandom(text);
                    if (s == null) fail?.Invoke("Tomt svar fra roulette.");
                    else ok?.Invoke(s);
                },
                e => fail?.Invoke(e.Contains("(404)")
                    ? "Ingen scener matcher filtrene — eller companion på Stash-serveren er for gammel til roulette."
                    : e));
        }

        public IEnumerator Facets(bool studios, string scopeId, Action<List<KalivStashFacet>> ok, Action<string> fail)
        {
            yield return Get(KalivStash.FacetsUrl(BaseUrl, studios, scopeId),
                text => ok?.Invoke(KalivStash.ParseFacets(text, studios)), fail);
        }

        /// <summary>Thumbnail, decoded and capped in size: many full-size Stash covers exhaust headset RAM.</summary>
        public IEnumerator Thumbnail(string url, Action<Texture2D> ok)
        {
            if (string.IsNullOrEmpty(url)) yield break;
            using var req = UnityWebRequest.Get(url);
            req.timeout = TimeoutSeconds;
            yield return req.SendWebRequest();
            if (req.result != UnityWebRequest.Result.Success) yield break;
            byte[] bytes = req.downloadHandler.data;
            if (bytes == null || bytes.Length == 0 || bytes.Length > 6 * 1024 * 1024) yield break;
            var tex = new Texture2D(2, 2, TextureFormat.RGBA32, false);
            if (!tex.LoadImage(bytes, true)) { Destroy(tex); yield break; }
            ok?.Invoke(tex);
        }

        public IEnumerator Progress(string sceneId, double position, double duration, bool finished)
        {
            using var req = new UnityWebRequest(Normalize(BaseUrl) + "/api/v1/progress", "POST");
            req.uploadHandler = new UploadHandlerRaw(Encoding.UTF8.GetBytes(KalivStash.ProgressBody(sceneId, position, duration, finished)));
            req.downloadHandler = new DownloadHandlerBuffer();
            req.SetRequestHeader("Content-Type", "application/json");
            req.timeout = TimeoutSeconds;
            yield return req.SendWebRequest();   // best effort: losing one resume point is harmless
        }

        private IEnumerator Get(string url, Action<string> ok, Action<string> fail)
        {
            if (string.IsNullOrWhiteSpace(BaseUrl)) { fail?.Invoke("Ingen Stash-server valgt. Tryk FIND STASH."); yield break; }
            using var req = UnityWebRequest.Get(url);
            req.timeout = TimeoutSeconds;
            yield return req.SendWebRequest();
            if (req.result != UnityWebRequest.Result.Success)
            {
                fail?.Invoke(req.responseCode == 0
                    ? "Stash-serveren svarer ikke (0). Kører companion, og er headsettet på samme netværk?"
                    : $"Stash-serveren svarede {req.responseCode} ({req.responseCode})");
                yield break;
            }
            ok?.Invoke(req.downloadHandler.text);
        }

        private static string Normalize(string v)
        {
            v = (v ?? "").Trim();
            while (v.EndsWith("/")) v = v.Substring(0, v.Length - 1);
            return v;
        }

        // ---- FIND STASH: UDP 8098, SkyPlayer's own protocol --------------------------------

        private volatile string _found;
        private volatile bool _probing;

        /// <summary>
        /// Broadcast SKYPLAYER_DISCOVER and take the first companion that answers. The same probe
        /// SkyPlayer's FIND SERVER sends, so one companion serves both apps unchanged. Global
        /// broadcast plus each interface's subnet broadcast: some routers pass only one of them.
        /// </summary>
        public IEnumerator Discover(float timeoutSeconds, Action<string> done)
        {
            _found = null;
            _probing = true;
            var thread = new Thread(() => Probe(timeoutSeconds)) { IsBackground = true, Name = "kaliv-stash-discovery" };
            thread.Start();
            float t = 0f;
            while (_probing && _found == null && t < timeoutSeconds + 0.5f)
            {
                t += Time.unscaledDeltaTime;
                yield return null;
            }
            _probing = false;
            done?.Invoke(_found);
        }

        private void Probe(float timeoutSeconds)
        {
            UdpClient udp = null;
            try
            {
                udp = new UdpClient(0) { EnableBroadcast = true };
                udp.Client.ReceiveTimeout = 400;
                byte[] msg = Encoding.UTF8.GetBytes(KalivStash.DiscoveryProbe);
                var targets = BroadcastTargets();
                var deadline = DateTime.UtcNow.AddSeconds(timeoutSeconds);
                while (_probing && _found == null && DateTime.UtcNow < deadline)
                {
                    foreach (var ep in targets)
                        try { udp.Send(msg, msg.Length, ep); } catch (Exception) { }
                    var until = DateTime.UtcNow.AddMilliseconds(700);
                    while (_probing && _found == null && DateTime.UtcNow < until)
                    {
                        try
                        {
                            var from = new IPEndPoint(IPAddress.Any, 0);
                            byte[] data = udp.Receive(ref from);
                            string url = KalivStash.ParseDiscoveryReply(Encoding.UTF8.GetString(data), from.Address.ToString());
                            if (url != null) _found = url;
                        }
                        catch (SocketException) { /* receive timeout: keep listening */ }
                    }
                }
            }
            catch (Exception e) { Debug.LogWarning("[KalivVR.Stash] discovery: " + e.Message); }
            finally
            {
                try { udp?.Close(); } catch (Exception) { }
                _probing = false;
            }
        }

        private static List<IPEndPoint> BroadcastTargets()
        {
            var list = new List<IPEndPoint> { new IPEndPoint(IPAddress.Broadcast, KalivStash.DiscoveryPort) };
            foreach (var (ip, mask) in KalivRigDiscovery.LocalInterfaces())
            {
                if (mask == null) continue;
                byte[] a = ip.GetAddressBytes(), m = mask.GetAddressBytes();
                if (m.Length != 4) continue;
                var bc = new byte[4];
                for (int i = 0; i < 4; i++) bc[i] = (byte)(a[i] | (byte)~m[i]);
                list.Add(new IPEndPoint(new IPAddress(bc), KalivStash.DiscoveryPort));
            }
            return list;
        }

        private void OnDestroy() => _probing = false;
    }
}
