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
    }
}
