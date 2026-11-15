using NUnit.Framework;

namespace Kaliv.VR.Tests
{
    public sealed class KalivKeyboardTests
    {
        [Test]
        public void TypesDanishLetters()
        {
            var kb = new KalivKeyboardModel();
            foreach (var k in new[] { "b", "l", "å", "b", "æ", "r", "g", "r", "ø", "d" }) kb.Press(k);
            Assert.AreEqual("blåbærgrød", kb.Text);
        }

        [Test]
        public void ShiftLastsForOneLetter_AsOnAPhone()
        {
            var kb = new KalivKeyboardModel();
            kb.Press(KalivKeyboardModel.Shift);
            Assert.AreEqual(KalivKeyboardModel.Layer.Upper, kb.Current);
            kb.Press("K");
            kb.Press("a");
            Assert.AreEqual("Ka", kb.Text);
            Assert.AreEqual(KalivKeyboardModel.Layer.Lower, kb.Current);
        }

        [Test]
        public void PromptStartsCapitalised_AddressAndCodeDoNot()
        {
            Assert.AreEqual(KalivKeyboardModel.Layer.Upper, new KalivKeyboardModel("", 2000, capitalizeFirst: true).Current);
            Assert.AreEqual(KalivKeyboardModel.Layer.Lower, new KalivKeyboardModel("", 200).Current);
            // Editing an existing text never forces a capital mid-sentence.
            Assert.AreEqual(KalivKeyboardModel.Layer.Lower, new KalivKeyboardModel("hej", 2000, capitalizeFirst: true).Current);
        }

        [Test]
        public void SymbolsLayer_CanTypeARigAddress()
        {
            var kb = new KalivKeyboardModel();
            foreach (var c in "http") kb.Press(c.ToString());
            kb.Press(KalivKeyboardModel.ToSymbols);
            StringAssert.Contains(":", kb.RowKeys(1));
            StringAssert.Contains("/", kb.RowKeys(1));
            kb.Press(":"); kb.Press("/"); kb.Press("/");
            foreach (var c in "192.168.1.10") kb.Press(c.ToString());
            kb.Press(":");
            foreach (var c in "8080") kb.Press(c.ToString());
            Assert.AreEqual("http://192.168.1.10:8080", kb.Text);
        }

        [Test]
        public void ShiftDoesNothingOnTheSymbolsLayer()
        {
            var kb = new KalivKeyboardModel();
            kb.Press(KalivKeyboardModel.ToSymbols);
            kb.Press(KalivKeyboardModel.Shift);
            Assert.AreEqual(KalivKeyboardModel.Layer.Symbols, kb.Current);
        }

        [Test]
        public void DeleteClearAndSpace()
        {
            var kb = new KalivKeyboardModel("ab");
            kb.Press(KalivKeyboardModel.Space);
            kb.Press(KalivKeyboardModel.Delete);
            kb.Press(KalivKeyboardModel.Delete);
            Assert.AreEqual("a", kb.Text);
            kb.Press(KalivKeyboardModel.Clear);
            Assert.AreEqual("", kb.Text);
            kb.Press(KalivKeyboardModel.Delete);   // on empty: no throw
            Assert.AreEqual("", kb.Text);
        }

        [Test]
        public void DeleteRemovesAWholeSurrogatePair()
        {
            var kb = new KalivKeyboardModel("a🙂");
            kb.Press(KalivKeyboardModel.Delete);
            Assert.AreEqual("a", kb.Text);
        }

        [Test]
        public void MaxLength_IsAWall_NotATruncation()
        {
            var kb = new KalivKeyboardModel("", 3);
            foreach (var c in "abcd") kb.Press(c.ToString());
            Assert.AreEqual("abc", kb.Text);
        }

        [Test]
        public void EveryRowFitsTheLayout()
        {
            var kb = new KalivKeyboardModel();
            foreach (var layer in new[] { KalivKeyboardModel.ToLetters, KalivKeyboardModel.ToSymbols })
            {
                kb.Press(layer);
                for (int r = 0; r < KalivKeyboardModel.Rows; r++)
                    Assert.LessOrEqual(kb.RowKeys(r).Length, KalivKeyboardModel.MaxKeysPerRow);
            }
        }
    }

    public sealed class KalivCapabilitiesTests
    {
        [Test]
        public void OnlyAnExplicitFalseBlocks()
        {
            // The load-bearing rule: unknown means available, so a failed probe never
            // switches off a working feature.
            Assert.IsNull(KalivCapabilities.Unknown.VoiceBlockedReason());
            Assert.IsNull(KalivCapabilities.FromHealthFull("{\"ok\":true}").VoiceBlockedReason());
            Assert.IsNull(KalivCapabilities.FromHealthFull("ikke json").VoiceBlockedReason());
            Assert.IsNull(KalivCapabilities.FromHealthFull("{\"capabilities\":{\"asr\":\"maybe\",\"tts\":1}}").VoiceBlockedReason());
        }

        [Test]
        public void FreshWorkerWithoutVoice_IsBlockedWithTheReason()
        {
            var caps = KalivCapabilities.FromHealthFull("{\"ok\":true,\"capabilities\":{\"asr\":false,\"tts\":false,\"pdf\":true}}");
            string reason = caps.VoiceBlockedReason();
            StringAssert.Contains("hverken tale-til-tekst eller tekst-til-tale", reason);
            StringAssert.Contains("faster-whisper og piper-tts", reason);
            CollectionAssert.AreEqual(new[] { "asr", "tts" }, caps.ExplicitlyMissing());
        }

        [Test]
        public void EitherHalfMissing_StillBlocks()
        {
            StringAssert.Contains("piper-tts",
                KalivCapabilities.FromHealthFull("{\"capabilities\":{\"asr\":true,\"tts\":false}}").VoiceBlockedReason());
            StringAssert.Contains("faster-whisper",
                KalivCapabilities.FromHealthFull("{\"capabilities\":{\"asr\":false,\"tts\":true}}").VoiceBlockedReason());
        }

        [Test]
        public void TopLevelBooleansAreNotCapabilities()
        {
            var caps = KalivCapabilities.FromHealthFull("{\"asr\":false,\"capabilities\":{\"tts\":true}}");
            Assert.IsTrue(caps.Supports("asr"));
        }
    }

    public sealed class KalivRigInfoTests
    {
        [Test]
        public void Sources_DefaultToEnabled_ForOlderRigs()
        {
            var list = KalivRigInfo.ParseRagSources(
                "{\"sources\":[{\"source\":\"a.pdf\",\"chunks\":12,\"last_ingested_at\":1.7e9}," +
                "{\"source\":\"b\",\"chunks\":3,\"last_ingested_at\":null,\"enabled\":false},{\"chunks\":1}]}");
            Assert.AreEqual(2, list.Count);
            Assert.IsTrue(list[0].Enabled);
            Assert.AreEqual(12, list[0].Chunks);
            Assert.IsFalse(list[1].Enabled);
            Assert.IsNull(list[1].LastIngestedAt);
        }

        [Test]
        public void ToolLayer_DefaultsToOff_WhenTheRigDoesNotSay()
        {
            // The safe direction for a switch that lets a model act.
            Assert.IsFalse(KalivRigInfo.ParseToolRegistry("{\"tools\":[]}").Enabled);
            var reg = KalivRigInfo.ParseToolRegistry(
                "{\"enabled\":true,\"tools\":[{\"name\":\"note_append\",\"risk\":\"write\",\"description\":\"x\",\"enabled\":true},{\"risk\":\"read\"}]}");
            Assert.IsTrue(reg.Enabled);
            Assert.AreEqual(1, reg.Tools.Count);
            Assert.AreEqual("write", reg.Tools[0].Risk);
        }
    }

    public sealed class KalivImageAndPersonTests
    {
        [Test]
        public void StereoImages_ShowOneEye()
        {
            Assert.AreEqual(new UnityEngine.Rect(0, 0, 0.5f, 1), KalivMediaGallery.ImageUvRect("left_right"));
            Assert.AreEqual(new UnityEngine.Rect(0, 0.5f, 1, 0.5f), KalivMediaGallery.ImageUvRect("top_bottom"));
            Assert.AreEqual(new UnityEngine.Rect(0, 0, 1, 1), KalivMediaGallery.ImageUvRect("mono"));
        }

        [Test]
        public void WhoAnswered_SurvivesARestart()
        {
            var c = new KalivConversation();
            c.Add(new KalivMessage("assistant", "hej") { Person = "Alva" });
            var restored = new KalivConversation();
            Assert.IsTrue(restored.LoadJson(c.ToJson()));
            Assert.AreEqual("Alva", restored.Messages[0].Person);
        }

        [Test]
        public void ToolTurn_ReadsThePerson()
        {
            var t = KalivToolTurn.Parse(KalivJson.TryParseObject(
                "{\"status\":\"answered\",\"answer\":\"x\",\"person\":{\"display_name\":\"Alva\",\"person_revision\":\"r1\"}}"));
            Assert.AreEqual("Alva", t.PersonName);
        }
    }
}
