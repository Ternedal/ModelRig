using NUnit.Framework;

namespace Kaliv.VR.Tests
{
    /// <summary>The Stash side, against the SkyPlayer companion's real shapes (SkyPlayer Models.cs).</summary>
    public sealed class KalivStashTests
    {
        private const string Base = "http://10.0.0.5:8099";

        [Test]
        public void OrderPills_MapExactlyLikeSkyPlayer()
        {
            Assert.AreEqual("", KalivStash.FilterFor(KalivStashOrder.All));
            Assert.AreEqual("created_at", KalivStash.SortFor(KalivStashOrder.Newest));
            Assert.AreEqual("favorites", KalivStash.FilterFor(KalivStashOrder.Favorites));
            Assert.AreEqual("vr", KalivStash.FilterFor(KalivStashOrder.Vr));
            Assert.AreEqual("random", KalivStash.SortFor(KalivStashOrder.Random));
        }

        [Test]
        public void RandomOrder_CarriesTheSeed_OtherOrdersDoNot()
        {
            string r = KalivStash.ScenesUrl(Base, KalivStashOrder.Random, null, null, null, 2, "4242");
            StringAssert.Contains("sort=random", r);
            StringAssert.Contains("seed=4242", r);
            StringAssert.Contains("page=2", r);
            StringAssert.DoesNotContain("seed=", KalivStash.ScenesUrl(Base, KalivStashOrder.Newest, null, null, null, 1, "4242"));
        }

        [Test]
        public void Filters_AreEscaped()
        {
            string u = KalivStash.ScenesUrl(Base + "/", KalivStashOrder.All, "æble & pære", "12", "7", 1, null);
            StringAssert.StartsWith(Base + "/api/v1/scenes?", u);
            StringAssert.Contains("q=%C3%A6ble%20%26%20p%C3%A6re", u);
            StringAssert.Contains("studio=12", u);
            StringAssert.Contains("tag=7", u);
        }

        [Test]
        public void Roulette_AndFacetUrls()
        {
            Assert.AreEqual(Base + "/api/v1/random", KalivStash.RandomUrl(Base, null, null, null));
            Assert.AreEqual(Base + "/api/v1/random?studio=3&tag=9", KalivStash.RandomUrl(Base, " ", "3", "9"));
            Assert.AreEqual(Base + "/api/v1/studios?tag=9", KalivStash.FacetsUrl(Base, true, "9"));
            Assert.AreEqual(Base + "/api/v1/tags?studio=3", KalivStash.FacetsUrl(Base, false, "3"));
        }

        [Test]
        public void Scenes_ParseTheCompanionShape()
        {
            var page = KalivStash.ParseScenes(
                "{\"count\":2,\"page\":1,\"perPage\":6,\"scenes\":[" +
                "{\"id\":\"41\",\"title\":\"A\",\"duration\":1800,\"resumeTime\":600,\"favorite\":true," +
                "\"thumbnailUrl\":\"http://h/t\",\"streamUrl\":\"http://h/s\",\"studio\":\"S\"," +
                "\"video\":{\"width\":5760,\"height\":2880,\"formatHint\":\"VR180_SBS\"}}," +
                "{\"id\":\"42\",\"title\":\"\",\"streamUrl\":\"\"}]}");
            Assert.AreEqual(2, page.Count);
            Assert.AreEqual(1, page.Scenes.Count);      // a scene with nothing to play is skipped
            var s = page.Scenes[0];
            Assert.AreEqual("VR180_SBS", s.FormatHint);
            Assert.IsTrue(s.IsImmersive);
            Assert.AreEqual(600, s.ResumeSeconds);
            Assert.AreEqual(5760, s.Width);
        }

        [Test]
        public void ASceneWithoutAFormat_PlaysFlat()
        {
            var s = KalivStash.ParseScene(KalivJson.TryParseObject("{\"id\":\"1\",\"streamUrl\":\"http://h/s\"}"));
            Assert.AreEqual("FLAT", s.FormatHint);
            Assert.IsFalse(s.IsImmersive);
            Assert.AreEqual("Scene 1", s.Title);
        }

        [Test]
        public void Roulette_AndFacets_Parse()
        {
            Assert.AreEqual("9", KalivStash.ParseRandom("{\"scene\":{\"id\":\"9\",\"streamUrl\":\"http://h/s\"},\"pool\":40}").Id);
            Assert.IsNull(KalivStash.ParseRandom("{\"pool\":0}"));
            var studios = KalivStash.ParseFacets("{\"studios\":[{\"id\":\"1\",\"name\":\"X\",\"sceneCount\":12},{\"name\":\"no id\"}]}", true);
            Assert.AreEqual(1, studios.Count);
            Assert.AreEqual(12, studios[0].SceneCount);
            Assert.AreEqual(1, KalivStash.ParseFacets("{\"tags\":[{\"id\":\"t\"}]}", false).Count);
        }

        [Test]
        public void Discovery_OnlyTheCompanionCounts()
        {
            Assert.AreEqual("http://10.0.0.5:8099",
                KalivStash.ParseDiscoveryReply("{\"service\":\"stash-skyplayer-companion\",\"name\":\"nas\",\"port\":8099}", "10.0.0.5"));
            Assert.AreEqual("http://10.0.0.5:9000",
                KalivStash.ParseDiscoveryReply("{\"service\":\"stash-skyplayer-companion\",\"port\":9000}", "10.0.0.5"));
            Assert.AreEqual("http://10.0.0.5:8099",   // a nonsense port falls back to the default
                KalivStash.ParseDiscoveryReply("{\"service\":\"stash-skyplayer-companion\",\"port\":99999}", "10.0.0.5"));
            Assert.IsNull(KalivStash.ParseDiscoveryReply("{\"service\":\"modelrig-server\"}", "10.0.0.5"));
            Assert.IsNull(KalivStash.ParseDiscoveryReply("garbage", "10.0.0.5"));
        }

        [Test]
        public void Resume_OnlyFromAMeaningfulPoint()
        {
            Assert.AreEqual(0, KalivStash.ResumeFrom(new KalivStashScene { ResumeSeconds = 5, DurationSeconds = 600 }));
            Assert.AreEqual(300, KalivStash.ResumeFrom(new KalivStashScene { ResumeSeconds = 300, DurationSeconds = 600 }));
            Assert.AreEqual(0, KalivStash.ResumeFrom(new KalivStashScene { ResumeSeconds = 595, DurationSeconds = 600 }));   // at the end: start over
        }

        [Test]
        public void ProgressBody_IsTheCompanionsShape()
        {
            var o = KalivJson.TryParseObject(KalivStash.ProgressBody("41", 123.5, 1800, false));
            Assert.AreEqual("41", KalivJson.Str(o, "sceneId"));
            Assert.AreEqual(123.5, KalivJson.Num(o, "positionSeconds"));
            Assert.AreEqual(1800, KalivJson.Num(o, "durationSeconds"));
            Assert.IsFalse(KalivJson.Bool(o, "finished"));
        }
    }
}
