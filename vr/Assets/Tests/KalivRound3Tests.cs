using NUnit.Framework;

namespace Kaliv.VR.Tests
{
    /// <summary>The rig-management parsers behind the RIG overlay, field for field against Android.</summary>
    public sealed class KalivRound3Tests
    {
        [Test]
        public void Persons_ListAndSelection()
        {
            var p = KalivRigInfo.ParsePersons(
                "{\"selected_person_id\":\"alva\",\"persons\":[" +
                "{\"person_id\":\"alva\",\"display_name\":\"Alva\",\"active_person_revision\":\"r3\"}," +
                "{\"person_id\":\"bo\",\"display_name\":\"\",\"active_person_revision\":null},{\"display_name\":\"uden id\"}]}");
            Assert.AreEqual("alva", p.SelectedId);
            Assert.AreEqual(2, p.Persons.Count);
            Assert.AreEqual("bo", p.Persons[1].DisplayName);   // no name: fall back to the id, never blank
            Assert.IsNull(p.Persons[1].ActiveRevision);
        }

        [Test]
        public void Persons_NoSelection()
        {
            Assert.IsNull(KalivRigInfo.ParsePersons("{\"selected_person_id\":\"\",\"persons\":[]}").SelectedId);
        }

        [Test]
        public void Devices_NeverCarryTokens_AndNeedAnId()
        {
            var d = KalivRigInfo.ParseDevices(
                "{\"devices\":[{\"id\":\"d1\",\"name\":\"kaliv-vr\",\"created_at\":\"2026-11-12\",\"last_seen\":\"\"},{\"name\":\"x\"},{\"id\":\"d2\"}]}");
            Assert.AreEqual(2, d.Count);
            Assert.IsNull(d[0].LastSeen);
            Assert.AreEqual("Uden navn", d[1].Name);
        }

        [Test]
        public void Models_InstalledAndRunning()
        {
            var installed = KalivRigInfo.ParseModels("{\"models\":[{\"name\":\"qwen3:8b\",\"size\":5200000000}]}");
            Assert.AreEqual(5200000000L, installed[0].SizeBytes);
            var running = KalivRigInfo.ParseModels(
                "{\"models\":[{\"name\":\"qwen3:8b\",\"size_vram\":6000000000,\"expires_at\":\"2026-11-13T19:00:00Z\"}]}");
            Assert.AreEqual(6000000000L, running[0].VramBytes);
        }

        [Test]
        public void Unload_ReportsWhatTheRigActuallyReleased()
        {
            var r = KalivRigInfo.ParseUnload("{\"unloaded\":[{\"name\":\"a\"},{\"name\":\"\"}],\"freed_bytes\":123,\"failed\":[\"b\"]}");
            CollectionAssert.AreEqual(new[] { "a" }, r.Unloaded);
            CollectionAssert.AreEqual(new[] { "b" }, r.Failed);
            Assert.AreEqual(123, r.FreedBytes);
        }

        [Test]
        public void Pull_SuccessOnlyFromOllamasFinalLine()
        {
            Assert.IsTrue(KalivRigInfo.TryParsePull("{\"status\":\"pulling abc\",\"completed\":50,\"total\":200}", out var p));
            Assert.IsFalse(p.IsSuccess);
            Assert.AreEqual(0.25f, p.Fraction, 1e-4);
            Assert.IsTrue(KalivRigInfo.TryParsePull("{\"status\":\"success\"}", out var s));
            Assert.IsTrue(s.IsSuccess);
            Assert.IsTrue(KalivRigInfo.TryParsePull("{\"error\":\"pull model manifest: file does not exist\"}", out var e));
            Assert.IsNotNull(e.Error);
            Assert.IsFalse(KalivRigInfo.TryParsePull("not json", out _));
        }

        [Test]
        public void Pull_VerifiesTheShelf_IncludingTheLatestTag()
        {
            Assert.IsTrue(KalivRigInfo.IsInstalled(new[] { "llama3:latest" }, "llama3"));
            Assert.IsTrue(KalivRigInfo.IsInstalled(new[] { "qwen3:8b" }, "qwen3:8b"));
            Assert.IsFalse(KalivRigInfo.IsInstalled(new[] { "qwen3:8b" }, "qwen3:14b"));
        }

        [Test]
        public void SystemStatus_UnknownStaysUnknown()
        {
            var s = KalivRigInfo.ParseSystemStatus(
                "{\"gpu\":{\"name\":\"RTX 4070\",\"temperature_c\":61,\"utilization_pct\":null,\"vram_total_mb\":12282,\"vram_used_mb\":7000},\"cpu\":{\"utilization_pct\":12.5},\"uptime_seconds\":3600}");
            Assert.AreEqual("RTX 4070", s.GpuName);
            Assert.AreEqual(61, s.GpuTempC);
            Assert.IsNull(s.GpuUtilPct);    // null means "cannot measure", not 0
            Assert.AreEqual(12.5, s.CpuPct);
            Assert.AreEqual(3600, s.UptimeSeconds);

            var none = KalivRigInfo.ParseSystemStatus("{\"gpu\":null}");
            Assert.IsNull(none.GpuName);
            Assert.IsNull(none.CpuPct);
            Assert.IsNull(none.UptimeSeconds);
        }

        [Test]
        public void Audit_DefaultsOriginToLocal()
        {
            var a = KalivRigInfo.ParseAudit(
                "{\"entries\":[{\"ts\":\"2026-11-13T10:00:00Z\",\"tool\":\"note_append\",\"risk\":\"write\",\"outcome\":\"approved\",\"result_summary\":\"ok\"}," +
                "{\"ts\":\"x\",\"tool\":\"pull_model\",\"outcome\":\"denied\",\"origin\":\"cloud\"}]}");
            Assert.AreEqual("local", a[0].Origin);
            Assert.AreEqual("cloud", a[1].Origin);
            Assert.AreEqual("ok", a[0].Summary);
        }

        [Test]
        public void Schedules_AndStatus()
        {
            var list = KalivRigInfo.ParseSchedules(
                "{\"schedules\":[{\"schedule_id\":\"s1\",\"label\":null,\"tool\":\"note_append\",\"cadence\":\"daily\"," +
                "\"due_at_local\":\"08:00\",\"enabled\":true,\"expired\":false,\"runs_used\":2,\"max_runs\":30,\"blocked_reason\":\"null\"}," +
                "{\"label\":\"uden id\"}]}");
            Assert.AreEqual(1, list.Count);
            Assert.IsNull(list[0].Label);
            Assert.IsNull(list[0].BlockedReason);   // org.json's literal "null" is not a reason
            Assert.AreEqual(30, list[0].MaxRuns);

            var st = KalivRigInfo.ParseScheduleStatus("{\"configured\":true,\"running\":false,\"last_error\":\"db locked\"}");
            Assert.IsTrue(st.Configured);
            Assert.IsFalse(st.Running);
            Assert.AreEqual("db locked", st.LastError);
        }

        [Test]
        public void PathSegments_CannotChangeTheEndpoint()
        {
            // Android found this class of bug with tests/workflow_client_path_segments.py.
            Assert.AreEqual("a%2F..%2Fb", ModelRigVrClient.Seg("a/../b"));
            Assert.AreEqual("a%20b", ModelRigVrClient.Seg("a b"));   // not '+': that is query encoding
        }

        [Test]
        public void Bytes_AreHumanReadable()
        {
            Assert.AreEqual("4.8 GB", KalivRigInfo.FormatBytes(5200000000L));
            Assert.AreEqual("500 MB", KalivRigInfo.FormatBytes(500L * 1024 * 1024));
        }
    }
}
