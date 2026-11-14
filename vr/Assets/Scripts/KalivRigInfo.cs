using System.Collections.Generic;

namespace Kaliv.VR
{
    /// <summary>A document source as the rig reports it.</summary>
    public sealed class KalivRagSource
    {
        public string Name;
        public int Chunks;
        public double? LastIngestedAt;
        /// <summary>Older rigs do not know the field; then the source counts as ON — what they actually do.</summary>
        public bool Enabled = true;
    }

    public sealed class KalivToolInfo
    {
        public string Name;
        public string Risk;
        public string Description;
        public bool Enabled;
    }

    /// <summary>The tool registry: the layer's kill switch, and each tool.</summary>
    public sealed class KalivToolRegistry
    {
        public bool Enabled;
        public List<KalivToolInfo> Tools = new List<KalivToolInfo>();
    }

    public sealed class KalivPerson
    {
        public string Id;
        public string DisplayName;
        public string ActiveRevision;
    }

    public sealed class KalivPersons
    {
        public string SelectedId;
        public List<KalivPerson> Persons = new List<KalivPerson>();
    }

    public sealed class KalivDevice
    {
        public string Id;
        public string Name;
        public string CreatedAt;
        public string LastSeen;
    }

    public sealed class KalivModel
    {
        public string Name;
        public long SizeBytes;
        /// <summary>Running models only: VRAM in use and when Ollama will unload it.</summary>
        public long VramBytes;
        public string ExpiresAt;
    }

    /// <summary>Every field nullable: the endpoint is fail-soft and says null for what it cannot measure.</summary>
    public sealed class KalivSystemStatus
    {
        public string GpuName;
        public int? GpuTempC;
        public int? GpuUtilPct;
        public int? VramTotalMb;
        public int? VramUsedMb;
        public double? CpuPct;
        public long? UptimeSeconds;
    }

    public sealed class KalivUnloadResult
    {
        public List<string> Unloaded = new List<string>();
        public long FreedBytes;
        public List<string> Failed = new List<string>();
    }

    public sealed class KalivAuditEntry
    {
        public string Ts;
        public string Tool;
        public string Risk;
        public string Outcome;
        public string Origin;
        public string Summary;
    }

    public sealed class KalivSchedule
    {
        public string Id;
        public string Label;
        public string Tool;
        public string Cadence;
        public string DueAtLocal;
        public string Risk;
        public bool Enabled;
        public bool Expired;
        public bool BudgetExhausted;
        public int RunsUsed;
        public int MaxRuns;
        public string BlockedReason;
    }

    public sealed class KalivScheduleStatus
    {
        public bool Configured;
        public bool Running;
        public string LastError;
    }

    /// <summary>One line of Ollama's pull stream, as relayed by the rig.</summary>
    public readonly struct KalivPullProgress
    {
        public readonly string Status;
        public readonly long Completed;
        public readonly long Total;
        public readonly string Error;
        public bool IsSuccess => Status == "success";
        public float Fraction => Total > 0 ? (float)System.Math.Min(1.0, (double)Completed / Total) : 0f;

        public KalivPullProgress(string status, long completed, long total, string error)
        {
            Status = status; Completed = completed; Total = total; Error = error;
        }
    }

    /// <summary>
    /// Parsers for the rig's settings endpoints, matching Android's ModelRigClient field by
    /// field: GET /api/v1/rag/sources and GET /api/v1/tools.
    ///
    /// Defaults follow Android where it matters. A source's `enabled` defaults to TRUE (an
    /// older rig that does not send it is serving that source). The tool layer's `enabled`
    /// defaults to FALSE: a registry that does not say the layer is on must not be shown
    /// as on — that is the safe direction for a switch that lets a model act.
    /// </summary>
    public static class KalivRigInfo
    {
        public static List<KalivRagSource> ParseRagSources(string body)
        {
            var list = new List<KalivRagSource>();
            var arr = KalivJson.Arr(KalivJson.TryParseObject(body), "sources");
            if (arr == null) return list;
            foreach (var item in arr)
            {
                var o = item as Dictionary<string, object>;
                string name = KalivJson.Str(o, "source");
                if (name.Length == 0) continue;
                list.Add(new KalivRagSource
                {
                    Name = name,
                    Chunks = KalivJson.Int(o, "chunks"),
                    LastIngestedAt = KalivJson.IsNull(o, "last_ingested_at") ? (double?)null : KalivJson.Num(o, "last_ingested_at"),
                    Enabled = KalivJson.Bool(o, "enabled", true),
                });
            }
            return list;
        }

        public static KalivToolRegistry ParseToolRegistry(string body)
        {
            var o = KalivJson.TryParseObject(body);
            var reg = new KalivToolRegistry { Enabled = KalivJson.Bool(o, "enabled", false) };
            var arr = KalivJson.Arr(o, "tools");
            if (arr == null) return reg;
            foreach (var item in arr)
            {
                var t = item as Dictionary<string, object>;
                string name = KalivJson.Str(t, "name");
                if (name.Length == 0) continue;
                reg.Tools.Add(new KalivToolInfo
                {
                    Name = name,
                    Risk = KalivJson.Str(t, "risk"),
                    Description = KalivJson.Str(t, "description"),
                    Enabled = KalivJson.Bool(t, "enabled"),
                });
            }
            return reg;
        }

        // ---- persons (#752) ---------------------------------------------------------------

        public static KalivPersons ParsePersons(string body)
        {
            var o = KalivJson.TryParseObject(body);
            var result = new KalivPersons { SelectedId = Blank(KalivJson.Str(o, "selected_person_id")) };
            var arr = KalivJson.Arr(o, "persons");
            if (arr == null) return result;
            foreach (var item in arr)
            {
                var p = ParsePerson(item as Dictionary<string, object>);
                if (p != null) result.Persons.Add(p);
            }
            return result;
        }

        public static KalivPerson ParsePerson(Dictionary<string, object> p)
        {
            string id = KalivJson.Str(p, "person_id");
            if (id.Length == 0) return null;
            string name = KalivJson.Str(p, "display_name");
            return new KalivPerson
            {
                Id = id,
                DisplayName = name.Length > 0 ? name : id,
                ActiveRevision = Blank(KalivJson.Str(p, "active_person_revision")),
            };
        }

        // ---- devices ----------------------------------------------------------------------

        /// <summary>The rig never hands out token hashes — only id, name and timestamps.</summary>
        public static List<KalivDevice> ParseDevices(string body)
        {
            var list = new List<KalivDevice>();
            var arr = KalivJson.Arr(KalivJson.TryParseObject(body), "devices");
            if (arr == null) return list;
            foreach (var item in arr)
            {
                var d = item as Dictionary<string, object>;
                string id = KalivJson.Str(d, "id");
                if (id.Length == 0) continue;
                string name = KalivJson.Str(d, "name");
                list.Add(new KalivDevice
                {
                    Id = id,
                    Name = name.Length > 0 ? name : "Uden navn",
                    CreatedAt = Blank(KalivJson.Str(d, "created_at")),
                    LastSeen = Blank(KalivJson.Str(d, "last_seen")),
                });
            }
            return list;
        }

        // ---- models -----------------------------------------------------------------------

        public static List<KalivModel> ParseModels(string body)
        {
            var list = new List<KalivModel>();
            var arr = KalivJson.Arr(KalivJson.TryParseObject(body), "models");
            if (arr == null) return list;
            foreach (var item in arr)
            {
                var m = item as Dictionary<string, object>;
                string name = KalivJson.Str(m, "name");
                if (name.Length == 0) continue;
                list.Add(new KalivModel
                {
                    Name = name,
                    SizeBytes = (long)KalivJson.Num(m, "size"),
                    VramBytes = (long)KalivJson.Num(m, "size_vram"),
                    ExpiresAt = Blank(KalivJson.Str(m, "expires_at")),
                });
            }
            return list;
        }

        public static KalivUnloadResult ParseUnload(string body)
        {
            var o = KalivJson.TryParseObject(body);
            var r = new KalivUnloadResult { FreedBytes = (long)KalivJson.Num(o, "freed_bytes") };
            var un = KalivJson.Arr(o, "unloaded");
            if (un != null)
                foreach (var item in un)
                {
                    string n = KalivJson.Str(item as Dictionary<string, object>, "name");
                    if (n.Length > 0) r.Unloaded.Add(n);
                }
            var failed = KalivJson.Arr(o, "failed");
            if (failed != null)
                foreach (var item in failed)
                    if (item is string s && s.Length > 0) r.Failed.Add(s);
            return r;
        }

        /// <summary>
        /// One pull line. An `error` line is a failure. The stream ENDING is not success — only
        /// Ollama's final {"status":"success"} is, and Android then also checks the model is
        /// actually on the shelf (audit 1.58.36 #7: the UI once said "Færdig" for a model that
        /// was never installed).
        /// </summary>
        public static bool TryParsePull(string line, out KalivPullProgress progress)
        {
            progress = default;
            var o = KalivJson.TryParseObject((line ?? "").Trim());
            if (o == null) return false;
            progress = new KalivPullProgress(
                KalivJson.Str(o, "status"),
                (long)KalivJson.Num(o, "completed"),
                (long)KalivJson.Num(o, "total"),
                Blank(KalivJson.Str(o, "error")));
            return true;
        }

        /// <summary>Ollama registers an untagged name as "name:latest".</summary>
        public static bool IsInstalled(IEnumerable<string> installed, string name)
        {
            foreach (var n in installed)
                if (n == name || n == name + ":latest") return true;
            return false;
        }

        // ---- system status ----------------------------------------------------------------

        public static KalivSystemStatus ParseSystemStatus(string body)
        {
            var o = KalivJson.TryParseObject(body);
            var gpu = KalivJson.Obj(o, "gpu");
            var cpu = KalivJson.Obj(o, "cpu");
            return new KalivSystemStatus
            {
                GpuName = Blank(KalivJson.Str(gpu, "name")),
                GpuTempC = IntOrNull(gpu, "temperature_c"),
                GpuUtilPct = IntOrNull(gpu, "utilization_pct"),
                VramTotalMb = IntOrNull(gpu, "vram_total_mb"),
                VramUsedMb = IntOrNull(gpu, "vram_used_mb"),
                CpuPct = KalivJson.IsNull(cpu, "utilization_pct") ? (double?)null : KalivJson.Num(cpu, "utilization_pct"),
                UptimeSeconds = KalivJson.IsNull(o, "uptime_seconds") ? (long?)null : (long)KalivJson.Num(o, "uptime_seconds"),
            };
        }

        // ---- tool audit -------------------------------------------------------------------

        /// <summary>The append-only audit log. Read-only: there is no delete path on the rig either.</summary>
        public static List<KalivAuditEntry> ParseAudit(string body)
        {
            var list = new List<KalivAuditEntry>();
            var arr = KalivJson.Arr(KalivJson.TryParseObject(body), "entries");
            if (arr == null) return list;
            foreach (var item in arr)
            {
                var e = item as Dictionary<string, object>;
                if (e == null) continue;
                list.Add(new KalivAuditEntry
                {
                    Ts = KalivJson.Str(e, "ts"),
                    Tool = KalivJson.Str(e, "tool"),
                    Risk = KalivJson.Str(e, "risk"),
                    Outcome = KalivJson.Str(e, "outcome"),
                    Origin = KalivJson.Str(e, "origin", "local"),
                    Summary = KalivJson.Str(e, "result_summary"),
                });
            }
            return list;
        }

        // ---- schedules --------------------------------------------------------------------

        public static List<KalivSchedule> ParseSchedules(string body)
        {
            var list = new List<KalivSchedule>();
            var arr = KalivJson.Arr(KalivJson.TryParseObject(body), "schedules");
            if (arr == null) return list;
            foreach (var item in arr)
            {
                var s = ParseSchedule(item as Dictionary<string, object>);
                if (s != null) list.Add(s);
            }
            return list;
        }

        public static KalivSchedule ParseSchedule(Dictionary<string, object> o)
        {
            string id = KalivJson.Str(o, "schedule_id");
            if (id.Length == 0) return null;
            return new KalivSchedule
            {
                Id = id,
                Label = Blank(KalivJson.Str(o, "label")),
                Tool = KalivJson.Str(o, "tool"),
                Cadence = KalivJson.Str(o, "cadence"),
                DueAtLocal = KalivJson.Str(o, "due_at_local"),
                Risk = KalivJson.Str(o, "risk"),
                Enabled = KalivJson.Bool(o, "enabled"),
                Expired = KalivJson.Bool(o, "expired"),
                BudgetExhausted = KalivJson.Bool(o, "budget_exhausted"),
                RunsUsed = KalivJson.Int(o, "runs_used"),
                MaxRuns = KalivJson.Int(o, "max_runs"),
                BlockedReason = Blank(KalivJson.Str(o, "blocked_reason")),
            };
        }

        public static KalivScheduleStatus ParseScheduleStatus(string body)
        {
            var o = KalivJson.TryParseObject(body);
            return new KalivScheduleStatus
            {
                Configured = KalivJson.Bool(o, "configured"),
                Running = KalivJson.Bool(o, "running"),
                LastError = Blank(KalivJson.Str(o, "last_error")),
            };
        }

        // ---- helpers ----------------------------------------------------------------------

        private static int? IntOrNull(Dictionary<string, object> o, string key) =>
            KalivJson.IsNull(o, key) ? (int?)null : KalivJson.Int(o, key);

        /// <summary>Android filters org.json's literal "null" string by hand; so do we.</summary>
        private static string Blank(string s) => string.IsNullOrWhiteSpace(s) || s == "null" ? null : s;

        public static string FormatBytes(long bytes)
        {
            if (bytes >= 1L << 30) return (bytes / (double)(1L << 30)).ToString("0.0", System.Globalization.CultureInfo.InvariantCulture) + " GB";
            if (bytes >= 1L << 20) return (bytes / (double)(1L << 20)).ToString("0", System.Globalization.CultureInfo.InvariantCulture) + " MB";
            return System.Math.Max(0, bytes / 1024) + " KB";
        }
    }
}
