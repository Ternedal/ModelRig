using System;
using System.Collections.Generic;
using UnityEngine;

namespace Kaliv.VR
{
    /// <summary>
    /// The RIG overlay: every rig surface the Android app has a screen for that makes sense
    /// in a headset — document sources, the tool registry, persons, models, system status,
    /// paired devices, schedules and the tool audit log.
    ///
    /// Two rules hold on every tab:
    /// * After a write, show what the RIG now reports, never what we asked for. A switch that
    ///   flips locally while the rig refused is worse than no switch.
    /// * Anything irreversible — deleting a model or a source, revoking a device — takes two
    ///   presses within a few seconds. A controller ray drifts; one stray trigger pull on a
    ///   list must not delete a 40 GB model.
    /// </summary>
    public sealed partial class KalivVrApp
    {
        private enum RigTab { Sources, Tools, Persons, Models, Status, Devices, Schedules, Log }

        private RigTab _rigTab = RigTab.Sources;
        private int _rigEpoch;          // stale responses from a tab you already left are dropped
        private string _armedKey;
        private float _armedUntil;
        private Action _cancelPull;
        private const float ArmSeconds = 4f;

        public void OpenRig()
        {
            if (!Paired) return;
            _panel.ShowRig(true);
            RigShowTab((int)_rigTab);
        }

        public void RigShowTab(int tab)
        {
            _rigTab = (RigTab)Mathf.Clamp(tab, 0, KalivVrPanel.RigTabs.Length - 1);
            _armedKey = null;
            int epoch = ++_rigEpoch;
            _panel.SetRigTab((int)_rigTab);
            _panel.SetRigRows(new List<KalivVrPanel.RigRow>());
            _panel.SetRigStatus("Henter …", false);

            switch (_rigTab)
            {
                case RigTab.Sources: LoadSources(epoch); break;
                case RigTab.Tools: LoadTools(epoch); break;
                case RigTab.Persons: LoadPersons(epoch); break;
                case RigTab.Models: LoadModels(epoch); break;
                case RigTab.Status: LoadStatus(epoch); break;
                case RigTab.Devices: LoadDevices(epoch); break;
                case RigTab.Schedules: LoadSchedules(epoch); break;
                case RigTab.Log: LoadLog(epoch); break;
            }
        }

        private bool Current(int epoch) => epoch == _rigEpoch;
        private void RigError(int epoch, string error) { if (Current(epoch)) _panel.SetRigStatus(Friendly(error), true); }
        private void ReloadTab() => RigShowTab((int)_rigTab);

        /// <summary>First press arms, second press within a few seconds fires. Returns true when it fires.</summary>
        private bool Confirm(string key)
        {
            if (_armedKey == key && Time.realtimeSinceStartup < _armedUntil)
            {
                _armedKey = null;
                return true;
            }
            _armedKey = key;
            _armedUntil = Time.realtimeSinceStartup + ArmSeconds;
            return false;
        }

        private bool Armed(string key) => _armedKey == key && Time.realtimeSinceStartup < _armedUntil;

        // =====================================================================================
        // KILDER — which documents VIDEN searches
        // =====================================================================================

        private void LoadSources(int epoch)
        {
            StartCoroutine(_client.RagSources(BaseUrl, Token,
                sources => { if (Current(epoch)) RenderSources(sources); },
                error => RigError(epoch, error)));
        }

        private void RenderSources(List<KalivRagSource> sources)
        {
            var rows = new List<KalivVrPanel.RigRow>
            {
                new KalivVrPanel.RigRow
                {
                    Label = "ALLE KILDER",
                    Selected = RagSource == null,
                    Toggle = "+ NOTE",
                    ToggleOn = true,
                    OnMain = () => { SetRagSource(null); RenderSources(sources); },
                    OnToggle = AddNote,
                },
            };
            bool filterStillExists = RagSource == null;
            foreach (var s in sources)
            {
                var src = s;
                if (src.Name == RagSource) filterStillExists = true;
                string delKey = "source:" + src.Name;
                rows.Add(new KalivVrPanel.RigRow
                {
                    Label = $"{src.Name}  ·  {src.Chunks} udsnit  ·  {(src.Enabled ? "hentes" : "slukket")}",
                    Selected = src.Name == RagSource,
                    Toggle = src.Enabled ? "SLUK" : "TÆND",
                    ToggleOn = src.Enabled,
                    OnMain = () => { SetRagSource(src.Name); RenderSources(sources); },
                    OnToggle = () => ToggleSource(src, sources),
                });
                rows.Add(new KalivVrPanel.RigRow
                {
                    Label = "     slet " + src.Name + " fra riggen",
                    Toggle = Armed(delKey) ? "TRYK IGEN" : "SLET",
                    ToggleOn = false,
                    OnToggle = () =>
                    {
                        if (Confirm(delKey)) DeleteSource(src);
                        else RenderSources(sources);
                    },
                });
            }
            if (!filterStillExists) SetRagSource(null);   // a filter on a deleted source finds nothing

            _panel.SetRigRows(rows, keepPage: true);
            _panel.SetRigStatus(sources.Count == 0
                ? "Riggen har ingen dokumenter endnu. Tilføj en note, eller tilføj filer fra telefonen."
                : "Vælg hvad VIDEN søger i. SLUK/TÆND bestemmer om riggen må bruge kilden — intet slettes af det.", false);
        }

        private void ToggleSource(KalivRagSource src, List<KalivRagSource> sources)
        {
            int epoch = _rigEpoch;
            _panel.SetRigStatus($"{(src.Enabled ? "Slukker" : "Tænder")} {src.Name} …", false);
            StartCoroutine(_client.SetRagSourceEnabled(BaseUrl, Token, src.Name, !src.Enabled,
                enabled => { src.Enabled = enabled; if (Current(epoch)) RenderSources(sources); },
                error => RigError(epoch, error)));
        }

        private void DeleteSource(KalivRagSource src)
        {
            int epoch = _rigEpoch;
            _panel.SetRigStatus($"Sletter {src.Name} …", false);
            StartCoroutine(_client.DeleteRagSource(BaseUrl, Token, src.Name,
                removed =>
                {
                    if (RagSource == src.Name) SetRagSource(null);
                    if (!Current(epoch)) return;
                    ReloadTab();
                    _panel.SetRigStatus($"{src.Name} slettet — {removed} udsnit fjernet.", false);
                },
                error => RigError(epoch, error)));
        }

        /// <summary>A typed note goes into the document index, under a source name of its own.</summary>
        private void AddNote()
        {
            _panel.RequestText("NOTE TIL DINE DOKUMENTER", "", 4000, "GEM", text =>
            {
                text = (text ?? "").Trim();
                if (text.Length == 0) { _panel.ShowRig(true); return; }
                string source = "vr-note-" + DateTime.Now.ToString("yyyy-MM-dd-HHmm");
                _panel.ShowRig(true);
                int epoch = _rigEpoch;
                _panel.SetRigStatus("Gemmer noten …", false);
                StartCoroutine(_client.IngestText(BaseUrl, Token, source, text,
                    added =>
                    {
                        if (!Current(epoch)) return;
                        ReloadTab();
                        _panel.SetRigStatus($"Noten er gemt som {source} ({added} udsnit).", false);
                    },
                    error => RigError(epoch, error)));
            });
        }

        private void SetRagSource(string source)
        {
            RagSource = source;
            PlayerPrefs.SetString(RagSourceKey, source ?? "");
            PlayerPrefs.Save();
            _panel.SetModes(RagMode, ToolsMode, RagSource);
        }

        // =====================================================================================
        // VÆRKTØJER — the rig's kill switch
        // =====================================================================================

        private void LoadTools(int epoch)
        {
            StartCoroutine(_client.ToolsList(BaseUrl, Token,
                reg => { if (Current(epoch)) RenderTools(reg); },
                error => RigError(epoch, error)));
        }

        private void RenderTools(KalivToolRegistry reg)
        {
            var rows = new List<KalivVrPanel.RigRow>
            {
                new KalivVrPanel.RigRow
                {
                    Label = "VÆRKTØJSLAGET (alle værktøjer)",
                    Toggle = reg.Enabled ? "TÆNDT" : "SLUKKET",
                    ToggleOn = reg.Enabled,
                    OnToggle = () => SetTools(!reg.Enabled, null),
                },
            };
            foreach (var t in reg.Tools)
            {
                var tool = t;
                string risk = string.IsNullOrEmpty(tool.Risk) ? "" : $"  ·  {tool.Risk}";
                rows.Add(new KalivVrPanel.RigRow
                {
                    Label = tool.Name + risk,
                    Toggle = tool.Enabled ? "TÆNDT" : "SLUKKET",
                    ToggleOn = tool.Enabled,
                    OnMain = () => _panel.SetRigStatus(
                        string.IsNullOrWhiteSpace(tool.Description) ? tool.Name : tool.Description, false),
                    OnToggle = () => SetTools(!tool.Enabled, tool.Name),
                });
            }
            _panel.SetRigRows(rows, keepPage: true);
            _panel.SetRigStatus(reg.Enabled
                ? "Riggens egen nødbremse: sluk et værktøj eller hele laget. Et slukket værktøj fortælles ikke engang til modellen."
                : "Værktøjslaget er slukket på riggen — VÆRKTØJER-ture bliver afvist, indtil det tændes.", false);
        }

        private void SetTools(bool enabled, string tool)
        {
            int epoch = _rigEpoch;
            _panel.SetRigStatus(enabled ? "Tænder …" : "Slukker …", false);
            StartCoroutine(_client.SetToolsEnabled(BaseUrl, Token, enabled, tool,
                reg => { if (Current(epoch)) RenderTools(reg); },
                error => RigError(epoch, error)));
        }

        // =====================================================================================
        // PERSONER — who Kaliv is
        // =====================================================================================

        private void LoadPersons(int epoch)
        {
            StartCoroutine(_client.Persons(BaseUrl, Token,
                persons => { if (Current(epoch)) RenderPersons(persons); },
                (status, error) =>
                {
                    if (!Current(epoch)) return;
                    if (status == 404) _panel.SetRigStatus("Denne rig har ikke Person Profile-registret endnu.", false);
                    else RigError(epoch, error);
                }));
        }

        private void RenderPersons(KalivPersons persons)
        {
            var rows = new List<KalivVrPanel.RigRow>();
            foreach (var p in persons.Persons)
            {
                var person = p;
                bool selected = person.Id == persons.SelectedId;
                rows.Add(new KalivVrPanel.RigRow
                {
                    Label = person.DisplayName + (person.ActiveRevision == null ? "  ·  ingen aktiv revision" : ""),
                    Selected = selected,
                    Toggle = selected ? "VALGT" : "VÆLG",
                    ToggleOn = selected,
                    OnToggle = () => { if (!selected) SelectPerson(person); },
                    OnMain = () => { if (!selected) SelectPerson(person); },
                });
            }
            _panel.SetRigRows(rows, keepPage: true);
            _panel.SetRigStatus(persons.Persons.Count == 0
                ? "Riggen har ingen personer endnu — Kaliv svarer med sin sædvanlige persona."
                : "Vælg hvem Kaliv er. Krop, stemme og personlighed skifter samlet, og avataren genindlæses af sig selv.", false);
        }

        private void SelectPerson(KalivPerson person)
        {
            int epoch = _rigEpoch;
            _panel.SetRigStatus($"Skifter til {person.DisplayName} …", false);
            StartCoroutine(_client.SelectPerson(BaseUrl, Token, person.Id,
                _ =>
                {
                    if (!Current(epoch)) return;
                    ReloadTab();
                    _panel.SetRigStatus($"{person.DisplayName} er valgt. Kroppen følger, når riggen har skiftet.", false);
                },
                error => RigError(epoch, error)));
        }

        // =====================================================================================
        // MODELLER — installed, loaded, download, delete
        // =====================================================================================

        private void LoadModels(int epoch)
        {
            List<KalivModel> installed = null, running = null;
            string err = null;
            void Done()
            {
                if (!Current(epoch) || installed == null || (running == null && err == null)) return;
                RenderModels(installed, running ?? new List<KalivModel>());
            }
            StartCoroutine(_client.ModelsDetailed(BaseUrl, Token,
                list => { installed = list; Done(); }, error => RigError(epoch, error)));
            // Running models are a nicety: a rig without /models/running still lists models.
            StartCoroutine(_client.RunningModels(BaseUrl, Token,
                list => { running = list; Done(); }, error => { err = error; Done(); }));
        }

        private void RenderModels(List<KalivModel> installed, List<KalivModel> running)
        {
            var loaded = new HashSet<string>();
            foreach (var r in running) loaded.Add(r.Name);

            var rows = new List<KalivVrPanel.RigRow>
            {
                new KalivVrPanel.RigRow
                {
                    Label = "+ HENT EN MODEL (fx qwen3:8b)",
                    Toggle = "HENT",
                    ToggleOn = true,
                    OnMain = PullModelPrompt,
                    OnToggle = PullModelPrompt,
                },
            };
            foreach (var m in installed)
            {
                var model = m;
                string key = "model:" + model.Name;
                bool active = model.Name == Model;
                string state = loaded.Contains(model.Name) ? "  ·  i hukommelsen" : "";
                rows.Add(new KalivVrPanel.RigRow
                {
                    Label = $"{model.Name}  ·  {KalivRigInfo.FormatBytes(model.SizeBytes)}{state}{(active ? "  ·  i brug" : "")}",
                    Selected = active,
                    Toggle = Armed(key) ? "TRYK IGEN" : "SLET",
                    ToggleOn = false,
                    OnMain = () =>
                    {
                        SelectModel(model.Name);
                        RefreshModels();
                        RenderModels(installed, running);
                    },
                    OnToggle = () =>
                    {
                        if (Confirm(key)) DeleteModel(model);
                        else RenderModels(installed, running);
                    },
                });
            }
            _panel.SetRigRows(rows, keepPage: true);
            _panel.SetRigStatus("Tryk på en model for at bruge den. SLET kræver to tryk og kan ikke fortrydes på riggen.", false);
        }

        private void PullModelPrompt()
        {
            if (_cancelPull != null) { _panel.SetRigStatus("En hentning kører allerede.", true); return; }
            _panel.RequestText("HENT MODEL — navn fra Ollama", "", 120, "HENT", name =>
            {
                _panel.ShowRig(true);
                name = (name ?? "").Trim();
                if (name.Length == 0) return;
                int epoch = _rigEpoch;
                _panel.SetRigStatus($"Henter {name} …", false);
                StartCoroutine(_client.PullModel(BaseUrl, Token, name,
                    p =>
                    {
                        if (!Current(epoch)) return;
                        string pct = p.Total > 0 ? $" {Mathf.RoundToInt(p.Fraction * 100)} %" : "";
                        _panel.SetRigStatus($"{name}: {p.Status}{pct}", false);
                    },
                    () =>
                    {
                        _cancelPull = null;
                        RefreshModels();
                        if (Current(epoch)) { ReloadTab(); _panel.SetRigStatus($"{name} er hentet og verificeret på riggen.", false); }
                    },
                    () => { _cancelPull = null; if (Current(epoch)) _panel.SetRigStatus("Hentningen blev stoppet.", false); },
                    error => { _cancelPull = null; RigError(epoch, error); },
                    cancel => _cancelPull = cancel));
            });
        }

        private void DeleteModel(KalivModel model)
        {
            int epoch = _rigEpoch;
            _panel.SetRigStatus($"Sletter {model.Name} …", false);
            StartCoroutine(_client.DeleteModel(BaseUrl, Token, model.Name,
                () =>
                {
                    RefreshModels();
                    if (!Current(epoch)) return;
                    ReloadTab();
                    _panel.SetRigStatus($"{model.Name} er slettet fra riggen.", false);
                },
                error => RigError(epoch, error)));
        }

        // =====================================================================================
        // STATUS — what the rig's hardware is doing
        // =====================================================================================

        private void LoadStatus(int epoch)
        {
            StartCoroutine(_client.SystemStatus(BaseUrl, Token,
                s => { if (Current(epoch)) RenderStatus(s); },
                (status, error) =>
                {
                    if (!Current(epoch)) return;
                    if (status == 404) _panel.SetRigStatus("Riggen er ældre end systemstatus — opdatér den for at se GPU og VRAM.", true);
                    else RigError(epoch, error);
                }));
        }

        private void RenderStatus(KalivSystemStatus s)
        {
            string Unknown(object v, string unit = "") => v == null ? "ukendt" : v + unit;
            string vram = s.VramUsedMb != null && s.VramTotalMb != null
                ? $"{s.VramUsedMb} / {s.VramTotalMb} MB"
                : "ukendt";
            string uptime = s.UptimeSeconds == null ? "ukendt"
                : TimeSpan.FromSeconds(s.UptimeSeconds.Value).ToString(@"d\.hh\:mm");

            var rows = new List<KalivVrPanel.RigRow>
            {
                new KalivVrPanel.RigRow { Label = "GPU  ·  " + (s.GpuName ?? "ukendt") },
                new KalivVrPanel.RigRow { Label = $"GPU-temperatur  ·  {Unknown(s.GpuTempC, " °C")}     belastning  ·  {Unknown(s.GpuUtilPct, " %")}" },
                new KalivVrPanel.RigRow { Label = "VRAM  ·  " + vram },
                new KalivVrPanel.RigRow { Label = "CPU  ·  " + (s.CpuPct == null ? "ukendt" : s.CpuPct.Value.ToString("0") + " %") },
                new KalivVrPanel.RigRow { Label = "Backend oppe i  ·  " + uptime },
                new KalivVrPanel.RigRow
                {
                    Label = "Frigør VRAM — riggen slipper alle indlæste modeller",
                    Toggle = "FRIGØR",
                    ToggleOn = true,
                    OnToggle = UnloadModels,
                },
                new KalivVrPanel.RigRow
                {
                    Label = "Opdatér målingen",
                    Toggle = "OPDATÉR",
                    ToggleOn = true,
                    OnToggle = ReloadTab,
                },
            };
            _panel.SetRigRows(rows);
            _panel.SetRigStatus("Målt på riggen nu. 'ukendt' betyder at riggen ikke kan måle det — ikke at noget er galt.", false);
        }

        private void UnloadModels()
        {
            int epoch = _rigEpoch;
            _panel.SetRigStatus("Frigør VRAM …", false);
            StartCoroutine(_client.UnloadModels(BaseUrl, Token,
                r =>
                {
                    if (!Current(epoch)) return;
                    string what = r.Unloaded.Count == 0 ? "Ingen modeller var indlæst."
                        : $"Sluppet: {string.Join(", ", r.Unloaded)} ({KalivRigInfo.FormatBytes(r.FreedBytes)}).";
                    string failed = r.Failed.Count == 0 ? "" : $" Kunne ikke slippe: {string.Join(", ", r.Failed)}.";
                    ReloadTab();
                    _panel.SetRigStatus(what + failed + " Næste besked indlæser modellen igen.", r.Failed.Count > 0);
                },
                (status, error) =>
                {
                    if (!Current(epoch)) return;
                    if (status == 404) _panel.SetRigStatus("Riggen er for gammel til at frigøre VRAM herfra.", true);
                    else RigError(epoch, error);
                }));
        }

        // =====================================================================================
        // ENHEDER — paired devices
        // =====================================================================================

        private void LoadDevices(int epoch)
        {
            StartCoroutine(_client.Devices(BaseUrl, Token,
                list => { if (Current(epoch)) RenderDevices(list); },
                error => RigError(epoch, error)));
        }

        private void RenderDevices(List<KalivDevice> devices)
        {
            var rows = new List<KalivVrPanel.RigRow>();
            foreach (var d in devices)
            {
                var device = d;
                string key = "device:" + device.Id;
                bool self = device.Id == DeviceId;
                string seen = device.LastSeen == null ? "" : "  ·  sidst set " + device.LastSeen;
                rows.Add(new KalivVrPanel.RigRow
                {
                    Label = device.Name + (self ? "  ·  DETTE HEADSET" : "") + seen,
                    Selected = self,
                    Toggle = Armed(key) ? "TRYK IGEN" : "FJERN",
                    ToggleOn = false,
                    OnToggle = () =>
                    {
                        if (Confirm(key)) RevokeDevice(device, self);
                        else RenderDevices(devices);
                    },
                });
            }
            _panel.SetRigRows(rows, keepPage: true);
            _panel.SetRigStatus(devices.Count == 0
                ? "Riggen rapporterer ingen parrede enheder."
                : "FJERN tilbagekalder adgangen med det samme — også midt i en samtale. To tryk.", false);
        }

        private void RevokeDevice(KalivDevice device, bool self)
        {
            int epoch = _rigEpoch;
            _panel.SetRigStatus($"Fjerner {device.Name} …", false);
            StartCoroutine(_client.RevokeDevice(BaseUrl, Token, device.Id,
                () =>
                {
                    // Revoking ourselves: the token is dead now, so behave as if the rig was forgotten.
                    if (self) { _panel.ShowRig(false); ForgetRig(); return; }
                    if (!Current(epoch)) return;
                    ReloadTab();
                    _panel.SetRigStatus($"{device.Name} har ikke længere adgang.", false);
                },
                error => RigError(epoch, error)));
        }

        // =====================================================================================
        // PLANER — scheduled tool runs
        // =====================================================================================

        private void LoadSchedules(int epoch)
        {
            KalivScheduleStatus status = null;
            StartCoroutine(_client.ScheduleStatus(BaseUrl, Token,
                s =>
                {
                    status = s;
                    StartCoroutine(_client.Schedules(BaseUrl, Token,
                        list => { if (Current(epoch)) RenderSchedules(status, list); },
                        (code, error) => RigError(epoch, error)));
                },
                (code, error) =>
                {
                    if (!Current(epoch)) return;
                    // The scheduler routes only exist when the rig has the scheduler configured.
                    if (code == 404) _panel.SetRigStatus("Planlæggeren er ikke slået til på denne rig.", false);
                    else RigError(epoch, error);
                }));
        }

        private void RenderSchedules(KalivScheduleStatus status, List<KalivSchedule> schedules)
        {
            var rows = new List<KalivVrPanel.RigRow>();
            foreach (var s in schedules)
            {
                var sch = s;
                string name = sch.Label ?? sch.Tool;
                string state = sch.Expired ? "udløbet" : sch.BudgetExhausted ? "kørsler brugt op"
                    : sch.BlockedReason ?? (sch.Enabled ? "næste " + sch.DueAtLocal : "på pause");
                bool canToggle = !sch.Expired && !sch.BudgetExhausted;
                rows.Add(new KalivVrPanel.RigRow
                {
                    Label = $"{name}  ·  {sch.Cadence}  ·  {state}  ·  {sch.RunsUsed}/{sch.MaxRuns}",
                    Toggle = canToggle ? (sch.Enabled ? "AKTIV" : "PAUSE") : null,
                    ToggleOn = sch.Enabled,
                    OnToggle = () => SetSchedule(sch, !sch.Enabled, status, schedules),
                });
            }
            _panel.SetRigRows(rows, keepPage: true);
            string head = !status.Configured ? "Planlæggeren er ikke konfigureret."
                : !status.Running ? "Planlæggeren kører ikke på riggen" + (status.LastError != null ? ": " + status.LastError : ".")
                : schedules.Count == 0 ? "Ingen planer endnu. Bed Kaliv om at planlægge noget med VÆRKTØJER slået til."
                : "Sæt en plan på pause eller genoptag den. Nye planer laves gennem Kaliv eller telefonen, hvor de godkendes.";
            _panel.SetRigStatus(head, status.Configured && !status.Running);
        }

        private void SetSchedule(KalivSchedule sch, bool enabled, KalivScheduleStatus status, List<KalivSchedule> all)
        {
            int epoch = _rigEpoch;
            _panel.SetRigStatus(enabled ? "Genoptager …" : "Sætter på pause …", false);
            StartCoroutine(_client.SetScheduleEnabled(BaseUrl, Token, sch.Id, enabled,
                updated =>
                {
                    if (!Current(epoch)) return;
                    int i = all.FindIndex(x => x.Id == sch.Id);
                    if (updated != null && i >= 0) all[i] = updated;
                    RenderSchedules(status, all);
                },
                error => RigError(epoch, error)));
        }

        // =====================================================================================
        // LOG — the tool audit log, read-only
        // =====================================================================================

        private void LoadLog(int epoch)
        {
            StartCoroutine(_client.ToolsAudit(BaseUrl, Token,
                entries => { if (Current(epoch)) RenderLog(entries); },
                error => RigError(epoch, error)));
        }

        private void RenderLog(List<KalivAuditEntry> entries)
        {
            var rows = new List<KalivVrPanel.RigRow>();
            foreach (var e in entries)
            {
                var entry = e;
                string origin = entry.Origin == "local" ? "" : "  ·  " + entry.Origin;
                rows.Add(new KalivVrPanel.RigRow
                {
                    Label = $"{ShortTs(entry.Ts)}  ·  {entry.Tool}  ·  {entry.Outcome}{origin}",
                    OnMain = () => _panel.SetRigStatus(
                        string.IsNullOrWhiteSpace(entry.Summary) ? $"{entry.Tool} · {entry.Risk} · {entry.Outcome}" : entry.Summary, false),
                });
            }
            _panel.SetRigRows(rows);
            _panel.SetRigStatus(entries.Count == 0
                ? "Ingen værktøjshandlinger er registreret endnu."
                : "Riggens uforanderlige log over forslag, godkendelser, afvisninger og fejl. Tryk på en linje for detaljer.", false);
        }

        private static string ShortTs(string ts)
        {
            if (DateTime.TryParse(ts, System.Globalization.CultureInfo.InvariantCulture,
                    System.Globalization.DateTimeStyles.AdjustToUniversal, out var t))
                return t.ToLocalTime().ToString("dd-MM HH:mm");
            return ts ?? "";
        }
    }
}
