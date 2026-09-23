using System;
using System.Collections;
using System.Text;
using UnityEngine;
using UnityEngine.Networking;

namespace Kaliv.VR.Rendering
{
    public sealed class KalivBodyFrameStream : MonoBehaviour
    {
        private KalivVrmRenderer _renderer;
        private string _baseUrl;
        private string _token;
        private Coroutine _loop;
        private int _generation;
        private long _lastTimestamp = -1;

        public bool IsConnected { get; private set; }
        public event Action<KalivBodyRenderFrame> FrameApplied;
        public event Action<string> StreamWarning;

        public void Configure(KalivVrmRenderer renderer, string baseUrl, string token)
        {
            _renderer = renderer;
            _baseUrl = (baseUrl ?? "").Trim().TrimEnd('/');
            _token = token ?? "";
        }

        public void StartStreaming()
        {
            StopStreaming();
            if (_renderer == null || string.IsNullOrWhiteSpace(_baseUrl) || string.IsNullOrWhiteSpace(_token))
                return;
            int generation = ++_generation;
            _loop = StartCoroutine(StreamForever(generation));
        }

        public void StopStreaming()
        {
            ++_generation;
            if (_loop != null)
            {
                StopCoroutine(_loop);
                _loop = null;
            }
            IsConnected = false;
            _lastTimestamp = -1;
        }

        private IEnumerator StreamForever(int generation)
        {
            string url = _baseUrl + "/api/v1/body/frames";
            while (enabled && generation == _generation)
            {
                using var request = UnityWebRequest.Get(url);
                request.redirectLimit = 0;
                request.timeout = 0;
                request.SetRequestHeader("Authorization", "Bearer " + _token.Trim());
                request.SetRequestHeader("Accept", "text/event-stream");
                request.downloadHandler = new SseHandler(this);
                IsConnected = false;
                _lastTimestamp = -1;

                yield return request.SendWebRequest();
                IsConnected = false;

                if (generation != _generation) yield break;
                if (request.result != UnityWebRequest.Result.Success)
                    StreamWarning?.Invoke($"BodyRig frame-stream afbrudt (HTTP {request.responseCode}).");

                yield return new WaitForSecondsRealtime(2f);
            }
        }

        internal void Accept(string json)
        {
            KalivBodyRenderFrame frame;
            try
            {
                frame = KalivBodyRenderFrame.Parse(json);
            }
            catch (Exception exc)
            {
                StreamWarning?.Invoke("Ugyldig BodyRig-frame droppet: " + exc.Message);
                return;
            }

            IsConnected = true;
            if (_renderer == null || !_renderer.IsBound) return;
            if (frame.timestamp_ms <= _lastTimestamp) return;

            _lastTimestamp = frame.timestamp_ms;
            _renderer.Apply(frame);
            FrameApplied?.Invoke(frame);
        }

        private sealed class SseHandler : DownloadHandlerScript
        {
            private readonly KalivBodyFrameStream _owner;
            private readonly StringBuilder _buffer = new();
            private readonly Decoder _decoder = Encoding.UTF8.GetDecoder();
            private readonly char[] _chars = new char[16 * 1024];

            public SseHandler(KalivBodyFrameStream owner) : base(new byte[16 * 1024])
            {
                _owner = owner;
            }

            protected override bool ReceiveData(byte[] data, int length)
            {
                if (data == null || length <= 0) return false;

                int chars = _decoder.GetChars(data, 0, length, _chars, 0, flush: false);
                if (chars > 0)
                    _buffer.Append(_chars, 0, chars);

                string text = _buffer.ToString().Replace("\r\n", "\n");
                int boundary;
                while ((boundary = text.IndexOf("\n\n", StringComparison.Ordinal)) >= 0)
                {
                    string block = text.Substring(0, boundary);
                    text = text.Substring(boundary + 2);
                    foreach (string line in block.Split('\n'))
                    {
                        if (line.StartsWith("data: ", StringComparison.Ordinal))
                            _owner.Accept(line.Substring(6));
                    }
                }
                _buffer.Clear();
                _buffer.Append(text);
                return true;
            }

            protected override void CompleteContent()
            {
                _decoder.Reset();
                _buffer.Clear();
            }
        }

        private void OnDisable() => StopStreaming();
    }
}
