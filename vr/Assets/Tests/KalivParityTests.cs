using System;
using System.Collections.Generic;
using System.Linq;
using NUnit.Framework;

namespace Kaliv.VR.Tests
{
    /// <summary>
    /// The pure logic behind RAG, tools, voice, conversation and media — the parts that can be
    /// proven on the desk before the headset. Each case pins a rule that exists for a reason,
    /// mostly one Android already paid for.
    /// </summary>
    public sealed class KalivJsonTests
    {
        [Test]
        public void ParsesNestedShapes()
        {
            var o = KalivJson.TryParseObject("{\"a\":{\"b\":[1,2.5,\"x\",true,null]}}");
            var arr = KalivJson.Arr(KalivJson.Obj(o, "a"), "b");
            Assert.AreEqual(5, arr.Count);
            Assert.AreEqual(1L, arr[0]);
            Assert.AreEqual(2.5, arr[1]);
            Assert.AreEqual("x", arr[2]);
            Assert.AreEqual(true, arr[3]);
            Assert.IsNull(arr[4]);
        }

        [Test]
        public void IntegersAndDecimalsStayDistinct()
        {
            // The media contract rejects 1.0 where it needs an integer; that is only possible
            // if the reader remembers which token it saw.
            var o = KalivJson.TryParseObject("{\"i\":3,\"d\":3.0,\"e\":3e0}");
            Assert.AreEqual(3L, KalivJson.StrictLong(o["i"]));
            Assert.IsNull(KalivJson.StrictLong(o["d"]));
            Assert.IsNull(KalivJson.StrictLong(o["e"]));
        }

        [Test]
        public void PresenceIsObservable()
        {
            // JsonUtility cannot tell absent from empty; the rig's protocols depend on it.
            var o = KalivJson.TryParseObject("{\"sources\":[]}");
            Assert.IsTrue(KalivJson.Has(o, "sources"));
            Assert.IsFalse(KalivJson.Has(o, "result"));
        }

        [Test]
        public void UnicodeAndEscapesRoundTrip()
        {
            string text = "Hej \"Kaliv\" — æøå\n\t\\ 🙂";
            string json = KalivJson.Serialize(new Dictionary<string, object> { ["t"] = text });
            Assert.AreEqual(text, KalivJson.Str(KalivJson.TryParseObject(json), "t"));
        }

        [Test]
        public void MalformedInputIsRejectedNotHalfRead()
        {
            Assert.IsNull(KalivJson.TryParseObject("{\"a\":1"));
            Assert.IsNull(KalivJson.TryParseObject("{\"a\":1} trailing"));
            Assert.IsNull(KalivJson.TryParseObject("[1,2]"));   // not an object
        }
    }

    public sealed class KalivStreamContractVoiceAndRagTests
    {
        [Test]
        public void SourcesHeader_IsRecognisedByShape()
        {
            var e = KalivStreamContract.Parse(
                "{\"sources\":[{\"source\":\"manual.pdf\",\"chunk_index\":2,\"score\":0.8},{\"source\":\"\"},{\"source\":\"noter\"}]}");
            Assert.AreEqual(KalivStreamEventKind.Sources, e.Kind);
            CollectionAssert.AreEqual(new[] { "manual.pdf", "noter" }, e.Names.ToArray());
        }

        [Test]
        public void SourcesHeader_AfterAPhase_IsStillSources()
        {
            // Android's old reader took "the first line" as the header; a stream that opened
            // with a phase lost it. Shape, not position.
            Assert.AreEqual(KalivStreamEventKind.Phase, KalivStreamContract.Parse("{\"phase\":\"searching\"}").Kind);
            Assert.AreEqual(KalivStreamEventKind.Sources, KalivStreamContract.Parse("{\"sources\":[]}").Kind);
        }

        [Test]
        public void VoiceTranscript()
        {
            var e = KalivStreamContract.Parse("{\"type\":\"transcript\",\"text\":\"hvad er klokken\"}");
            Assert.AreEqual(KalivStreamEventKind.Transcript, e.Kind);
            Assert.AreEqual("hvad er klokken", e.Text);
        }

        [Test]
        public void VoiceChunk_CarriesOrderAudioAndUtterance()
        {
            var e = KalivStreamContract.Parse(
                "{\"type\":\"chunk\",\"index\":3,\"text\":\"Den er tolv.\",\"audio_base64\":\"UklGRg==\",\"utterance_id\":\"u-9\",\"ttfa_s\":1.2}");
            Assert.AreEqual(KalivStreamEventKind.Chunk, e.Kind);
            Assert.AreEqual(3, e.Index);
            Assert.AreEqual("Den er tolv.", e.Text);
            Assert.AreEqual("UklGRg==", e.AudioB64);
            Assert.AreEqual("u-9", e.UtteranceId);
        }

        [Test]
        public void VoiceChunk_FromOlderRig_HasNoUtterance()
        {
            var e = KalivStreamContract.Parse("{\"type\":\"chunk\",\"index\":0,\"text\":\"Hej\",\"audio_base64\":\"\"}");
            Assert.IsNull(e.UtteranceId);
        }

        [Test]
        public void TypedDone_CarriesTheWholeReply()
        {
            var e = KalivStreamContract.Parse("{\"type\":\"done\",\"reply\":\"Den er tolv.\",\"model\":\"qwen\",\"via_cloud\":false}");
            Assert.AreEqual(KalivStreamEventKind.Done, e.Kind);
            Assert.AreEqual("Den er tolv.", e.Reply);
            Assert.AreEqual("qwen", e.Model);
            Assert.AreEqual("", e.Text);   // no trailing delta on a typed done
        }

        [Test]
        public void TypedError_CarriesItsStatus()
        {
            var e = KalivStreamContract.Parse("{\"type\":\"error\",\"status\":503,\"detail\":\"TTS not installed\"}");
            Assert.AreEqual(KalivStreamEventKind.Failure, e.Kind);
            Assert.AreEqual(503, e.Status);
        }
    }

    public sealed class KalivTurnTests
    {
        [Test]
        public void ToolsWin_ThenKnowledge_ThenChat()
        {
            Assert.AreEqual(KalivTurnRoute.Tools, KalivTurnPlan.For(true, true).Route);
            Assert.IsTrue(KalivTurnPlan.For(true, true).ToolsWithRag);
            Assert.IsFalse(KalivTurnPlan.For(true, false).ToolsWithRag);
            Assert.AreEqual(KalivTurnRoute.Rag, KalivTurnPlan.For(false, true).Route);
            Assert.AreEqual(KalivTurnRoute.Chat, KalivTurnPlan.For(false, false).Route);
        }

        [Test]
        public void StatusStrings_MatchAndroid()
        {
            Assert.AreEqual("Kaliv tænker …", KalivTurnStatus.ForPhase("generating"));
            Assert.AreEqual("Søger i din viden …", KalivTurnStatus.ForPhase("searching"));
            Assert.AreEqual("Kører værktøj …", KalivTurnStatus.ForPhase("tool_run"));
        }

        [Test]
        public void UnknownPhase_KeepsTheCurrentStatus()
        {
            // A newer worker's phase must not blank the UI or force a guess.
            Assert.IsNull(KalivTurnStatus.ForPhase("reticulating_splines"));
        }

        [Test]
        public void ToolTurn_Proposal()
        {
            var t = KalivToolTurn.Parse(KalivJson.TryParseObject(
                "{\"status\":\"confirmation_required\",\"confirmation_id\":\"c-1\",\"tool\":\"note_append\"," +
                "\"risk\":\"write\",\"impact\":\"append\",\"summary\":\"Tilføj linje til noter\",\"expires_in_seconds\":120}"));
            Assert.IsTrue(t.NeedsConfirmation);
            Assert.AreEqual("note_append", t.Tool);
            Assert.AreEqual("append", t.Impact);
            Assert.AreEqual(120, t.ExpiresInSeconds);
        }

        [Test]
        public void ToolTurn_ConfirmationRequiredWithoutId_IsNotActionable()
        {
            // Without an id there is nothing to approve; never show a card that cannot work.
            var t = KalivToolTurn.Parse(KalivJson.TryParseObject("{\"status\":\"confirmation_required\"}"));
            Assert.IsFalse(t.NeedsConfirmation);
        }

        [Test]
        public void ToolTurn_ExplicitNullTool_ReadsAsNoTool()
        {
            var t = KalivToolTurn.Parse(KalivJson.TryParseObject("{\"status\":\"answered\",\"tool\":null,\"answer\":\"Hej\"}"));
            Assert.IsNull(t.Tool);
            Assert.AreEqual("Hej", t.Answer);
        }

        [Test]
        public void ToolTurn_Context_FailsClosedPerExcerpt()
        {
            var t = KalivToolTurn.Parse(KalivJson.TryParseObject(
                "{\"status\":\"answered\",\"sources\":[\"a\"],\"context\":[{\"source\":\"a\",\"chunk_index\":null,\"score\":0.5,\"excerpt\":\"x\"},{\"score\":1}]}"));
            Assert.AreEqual(1, t.Context.Count);
            Assert.IsNull(t.Context[0].ChunkIndex);
            CollectionAssert.AreEqual(new[] { "a" }, t.Sources);
        }

        [Test]
        public void ToolStream_PhaseResultAndError()
        {
            Assert.AreEqual(KalivToolStream.LineKind.Phase, KalivToolStream.Parse("{\"phase\":\"tool_run\"}", out var p, out _));
            Assert.AreEqual("tool_run", p);
            Assert.AreEqual(KalivToolStream.LineKind.Result,
                KalivToolStream.Parse("{\"result\":{\"status\":\"answered\",\"answer\":\"ok\"}}", out _, out var r));
            Assert.AreEqual("ok", r.Answer);
            Assert.AreEqual(KalivToolStream.LineKind.Failure,
                KalivToolStream.Parse("{\"error\":\"tools disabled\",\"status\":403}", out var e, out _));
            Assert.AreEqual("tools disabled", e);
        }
    }

    public sealed class KalivConversationTests
    {
        private static KalivConversation Convo(params (string role, string text, bool error)[] msgs)
        {
            var c = new KalivConversation();
            foreach (var m in msgs) c.Add(new KalivMessage(m.role, m.text) { Error = m.error });
            return c;
        }

        [Test]
        public void ErrorBubbles_AreNeverSentAsHistory()
        {
            var c = Convo(("user", "hej", false), ("assistant", "riggen svarede ikke", true), ("user", "hej igen", false));
            var h = c.History();
            Assert.AreEqual(2, h.Count);
            Assert.IsFalse(h.Any(x => x.content.Contains("svarede ikke")));
        }

        [Test]
        public void History_IsBoundedByCountAndCharacters()
        {
            var c = new KalivConversation();
            for (int i = 0; i < 30; i++) c.Add(new KalivMessage(i % 2 == 0 ? "user" : "assistant", "m" + i));
            Assert.AreEqual(KalivConversation.MaxHistoryMessages, c.History().Count);
            Assert.AreEqual("m29", c.History().Last().content);

            var big = new List<(string, string)> { ("user", new string('a', 20000)), ("assistant", new string('b', 20000)) };
            var trimmed = KalivConversation.Trim(big, 20, 24000);
            Assert.AreEqual(1, trimmed.Count);       // trimmed from the FRONT
            Assert.AreEqual('b', trimmed[0].Item2[0]);
        }

        [Test]
        public void History_ExcludeLast_DropsTheCurrentMessage()
        {
            var c = Convo(("user", "a", false), ("assistant", "b", false), ("user", "c", false));
            Assert.AreEqual(2, c.History(excludeLast: true).Count);
        }

        [Test]
        public void Retry_OnlyOfferedAfterAFailedOrMissingAnswer()
        {
            Assert.IsFalse(Convo(("user", "a", false), ("assistant", "fint svar", false)).TryGetRetry(out _));
            Assert.IsTrue(Convo(("user", "a", false), ("assistant", "fejl", true)).TryGetRetry(out var p1));
            Assert.AreEqual("a", p1);
            Assert.IsTrue(Convo(("user", "b", false)).TryGetRetry(out var p2));
            Assert.AreEqual("b", p2);
        }

        [Test]
        public void PrepareRetry_RemovesTheFailedAnswerSoTheQuestionIsNotDuplicated()
        {
            var c = Convo(("user", "a", false), ("assistant", "fejl", true));
            c.PrepareRetry();
            Assert.AreEqual(1, c.Count);
            Assert.AreEqual("user", c.Messages[0].Role);
        }

        [Test]
        public void Persistence_RoundTrips_WithoutErrors()
        {
            var c = Convo(("user", "hej æøå", false), ("assistant", "fejl", true), ("assistant", "svar", false));
            c.Messages[2].Sources.Add("manual.pdf");
            c.Messages[2].Tool = "note_append";
            var restored = new KalivConversation();
            Assert.IsTrue(restored.LoadJson(c.ToJson()));
            Assert.AreEqual(2, restored.Count);   // the error bubble is UI, not conversation
            Assert.AreEqual("hej æøå", restored.Messages[0].Text);
            CollectionAssert.AreEqual(new[] { "manual.pdf" }, restored.Messages[1].Sources);
            Assert.AreEqual("note_append", restored.Messages[1].Tool);
            Assert.AreEqual(c.ConversationId, restored.ConversationId);
        }

        [Test]
        public void Persistence_RejectsForeignOrBrokenFiles()
        {
            var c = Convo(("user", "behold mig", false));
            Assert.IsFalse(c.LoadJson("{\"schema\":\"noget-andet\",\"messages\":[]}"));
            Assert.IsFalse(c.LoadJson("ikke json"));
            Assert.AreEqual(1, c.Count);   // a bad file never wipes what is there
        }
    }

    public sealed class KalivWavTests
    {
        [Test]
        public void EncodeDecode_RoundTripsAtTheRigRate()
        {
            var tone = new float[16000];
            for (int i = 0; i < tone.Length; i++) tone[i] = 0.5f * (float)Math.Sin(i * 0.1);
            var pcm = KalivWav.Decode(KalivWav.EncodeForRig(tone, 16000));
            Assert.AreEqual(1, pcm.Channels);
            Assert.AreEqual(16000, pcm.SampleRate);
            Assert.AreEqual(tone.Length, pcm.Samples.Length);
            Assert.AreEqual(tone[100], pcm.Samples[100], 1e-3);
        }

        [Test]
        public void MicrophoneRate_IsResampledTo16k()
        {
            // The Quest may record at 48 kHz; the rig's ASR expects 16 kHz.
            var pcm = KalivWav.Decode(KalivWav.EncodeForRig(new float[48000], 48000));
            Assert.AreEqual(16000, pcm.SampleRate);
            Assert.AreEqual(16000, pcm.Samples.Length);
        }

        [Test]
        public void Decode_ReadsTheHeader_NotAnAssumedRate()
        {
            // TTS backends differ: a clip built at the wrong rate plays as chipmunk speech.
            var stereo22k = KalivWav.EncodePcm16(new float[22050 * 2], 2, 22050);
            var pcm = KalivWav.Decode(stereo22k);
            Assert.AreEqual(2, pcm.Channels);
            Assert.AreEqual(22050, pcm.SampleRate);
            Assert.AreEqual(1f, pcm.Seconds, 1e-3);
        }

        [Test]
        public void Decode_SkipsUnknownChunks()
        {
            var wav = KalivWav.EncodePcm16(new[] { 0.25f, -0.25f }, 1, 16000);
            // Insert a LIST chunk between fmt and data, as many encoders do.
            var list = new byte[] { (byte)'L', (byte)'I', (byte)'S', (byte)'T', 4, 0, 0, 0, 1, 2, 3, 4 };
            var spliced = wav.Take(36).Concat(list).Concat(wav.Skip(36)).ToArray();
            var pcm = KalivWav.Decode(spliced);
            Assert.AreEqual(2, pcm.Samples.Length);
            Assert.AreEqual(0.25f, pcm.Samples[0], 1e-3);
        }

        [Test]
        public void Decode_RejectsGarbage()
        {
            Assert.Throws<FormatException>(() => KalivWav.Decode(new byte[] { 1, 2, 3 }));
            Assert.Throws<FormatException>(() => KalivWav.Decode(System.Text.Encoding.ASCII.GetBytes("RIFF0000WAVExxxx")));
        }
    }

    public sealed class KalivMediaGalleryTests
    {
        private const string Good =
            "{\"id\":\"v1\",\"kind\":\"video\",\"mime_type\":\"video/mp4\",\"created_at\":\"2026-11-12T10:00:00Z\"," +
            "\"size_bytes\":1048576,\"width\":3840,\"height\":1920,\"duration_seconds\":61.5," +
            "\"projection\":\"equirectangular_180\",\"stereo\":\"left_right\",\"thumbnail_id\":\"t1\"," +
            "\"playback\":{\"supports_range\":true},\"url\":\"/api/v1/media/v1\",\"thumbnail_url\":\"/api/v1/media/t1\"}";

        private static string Page(string items, string cursor = "null") =>
            "{\"schema\":\"kaliv-media-gallery/v1\",\"items\":[" + items + "],\"next_cursor\":" + cursor + "}";

        [Test]
        public void ValidItem_Parses_AndMapsToTheEngineVocabulary()
        {
            var page = KalivMediaGallery.ParsePage(Page(Good));
            Assert.AreEqual(1, page.Items.Count);
            Assert.AreEqual("VR180_SBS", page.Items[0].FormatHint);
            Assert.IsNull(page.NextCursor);
        }

        [Test]
        public void InvalidItems_AreSkippedAndCounted_NeverTakingThePageDown()
        {
            string decimalSize = Good.Replace("1048576", "1048576.0");
            string offsetDate = Good.Replace("\"id\":\"v1\"", "\"id\":\"v2\"").Replace("/media/v1\"", "/media/v2\"")
                                    .Replace("10:00:00Z", "10:00:00+01:00");
            string pathMismatch = Good.Replace("\"id\":\"v1\"", "\"id\":\"v3\"");   // url still says v1
            string duplicate = Good;
            var page = KalivMediaGallery.ParsePage(Page(string.Join(",", Good, decimalSize, offsetDate, pathMismatch, duplicate)));
            Assert.AreEqual(1, page.Items.Count);
            Assert.AreEqual(4, page.Skipped);
        }

        [Test]
        public void PageLevelDamage_RejectsThePage()
        {
            Assert.Throws<FormatException>(() => KalivMediaGallery.ParsePage("{\"schema\":\"v2\",\"items\":[],\"next_cursor\":null}"));
            Assert.Throws<FormatException>(() => KalivMediaGallery.ParsePage("{\"schema\":\"kaliv-media-gallery/v1\",\"items\":[]}"));
            Assert.Throws<FormatException>(() => KalivMediaGallery.ParsePage(Page("", "\"has space\"")));
        }

        [Test]
        public void UnsafeIds_NeverBecomePaths()
        {
            Assert.IsFalse(KalivMediaGallery.IsSafeId("../etc"));
            Assert.IsFalse(KalivMediaGallery.IsSafeId("a/b"));
            Assert.Throws<ArgumentException>(() => KalivMediaGallery.MediaPath("a b"));
        }

        [Test]
        public void FormatsTheEngineCannotRender_AreRefusedNotGuessed()
        {
            // FromHint falls back to flat 2D on unknown names, which would show both eyes.
            Assert.IsNull(KalivMediaGallery.FormatHintFor("flat", "top_bottom"));
            Assert.IsNull(KalivMediaGallery.FormatHintFor("equirectangular_360", "top_bottom"));
            Assert.AreEqual("FLAT", KalivMediaGallery.FormatHintFor("flat", "mono"));
            Assert.AreEqual("SBS_3D", KalivMediaGallery.FormatHintFor("flat", "left_right"));
            Assert.AreEqual("OU_TB", KalivMediaGallery.FormatHintFor("equirectangular_180", "top_bottom"));
            Assert.AreEqual("VR360_MONO", KalivMediaGallery.FormatHintFor("equirectangular_360", "mono"));
        }

        [Test]
        public void ImageWithDuration_IsAContractBreak()
        {
            string image = Good.Replace("\"kind\":\"video\"", "\"kind\":\"image\"").Replace("video/mp4", "image/png");
            Assert.AreEqual(1, KalivMediaGallery.ParsePage(Page(image)).Skipped);
        }
    }
}
