using NUnit.Framework;

namespace Kaliv.VR.Tests
{
    /// <summary>
    /// The VR half of the shared stream contract, tested against the same cases as the
    /// Android suite. Three clients read one wire format; if they disagree about what a
    /// finished answer is, they disagree about whether the user got a whole one.
    ///
    /// Each case here is a failure mode that has actually reached a user on one client or
    /// another, so they are regression tests, not illustrations.
    /// </summary>
    public sealed class KalivStreamContractTests
    {
        // --- lines that carry nothing -----------------------------------------------

        [Test]
        public void BlankLine_IsIgnored()
        {
            Assert.AreEqual(KalivStreamEventKind.Ignored, KalivStreamContract.Parse("").Kind);
            Assert.AreEqual(KalivStreamEventKind.Ignored, KalivStreamContract.Parse("   ").Kind);
            Assert.AreEqual(KalivStreamEventKind.Ignored, KalivStreamContract.Parse(null).Kind);
        }

        [Test]
        public void NonJsonLine_IsIgnored()
        {
            // Proxies and load balancers inject keep-alive comments and plain text. They
            // must not be mistaken for content, or they end up printed in the answer.
            Assert.AreEqual(KalivStreamEventKind.Ignored, KalivStreamContract.Parse(": keep-alive").Kind);
            Assert.AreEqual(KalivStreamEventKind.Ignored, KalivStreamContract.Parse("OK").Kind);
        }

        [Test]
        public void MalformedJson_IsIgnored_NotThrown()
        {
            // A half-written line at the tail of a dropped body must not take the turn down.
            Assert.AreEqual(KalivStreamEventKind.Ignored, KalivStreamContract.Parse("{\"message\":{\"cont").Kind);
        }

        // --- content ------------------------------------------------------------------

        [Test]
        public void MessageContent_IsADelta()
        {
            var e = KalivStreamContract.Parse("{\"message\":{\"content\":\"Hej \"}}");
            Assert.AreEqual(KalivStreamEventKind.Delta, e.Kind);
            Assert.AreEqual("Hej ", e.Text);
        }

        [Test]
        public void EmptyContent_IsIgnored_NotADelta()
        {
            // Ollama emits empty-content lines while loading. Scoring them as content makes
            // a stream that never produced an answer look like a truncated one.
            Assert.AreEqual(
                KalivStreamEventKind.Ignored,
                KalivStreamContract.Parse("{\"message\":{\"content\":\"\"}}").Kind);
        }

        // --- completion ---------------------------------------------------------------

        [Test]
        public void DoneFlag_IsTerminal()
        {
            var e = KalivStreamContract.Parse("{\"done\":true,\"message\":{\"content\":\"\"}}");
            Assert.AreEqual(KalivStreamEventKind.Done, e.Kind);
            Assert.AreEqual("", e.Text);
        }

        [Test]
        public void DoneFlag_CarriesItsTrailingContent()
        {
            // Ollama may put the final token on the terminal line. Dropping it silently
            // truncates the answer by a word.
            var e = KalivStreamContract.Parse("{\"done\":true,\"message\":{\"content\":\"!\"}}");
            Assert.AreEqual(KalivStreamEventKind.Done, e.Kind);
            Assert.AreEqual("!", e.Text);
        }

        [Test]
        public void TypedDoneEvent_IsTerminal()
        {
            var e = KalivStreamContract.Parse("{\"type\":\"done\"}");
            Assert.AreEqual(KalivStreamEventKind.Done, e.Kind);
            Assert.AreEqual("", e.Text);
        }

        // --- failure ------------------------------------------------------------------

        [Test]
        public void TypedErrorEvent_CarriesItsDetail()
        {
            var e = KalivStreamContract.Parse("{\"type\":\"error\",\"detail\":\"model not found\"}");
            Assert.AreEqual(KalivStreamEventKind.Failure, e.Kind);
            Assert.AreEqual("model not found", e.Info);
        }

        [Test]
        public void TypedErrorEvent_WithoutDetail_StillReadsAsFailure()
        {
            var e = KalivStreamContract.Parse("{\"type\":\"error\"}");
            Assert.AreEqual(KalivStreamEventKind.Failure, e.Kind);
            Assert.AreEqual("ukendt fejl", e.Info);
        }

        [Test]
        public void BareErrorLine_IsAFailure()
        {
            // The regression that prompted the shared contract: this line has no
            // message.content, so a naive reader scores it as an empty delta and drops it —
            // the stream then ends with nothing on screen and no explanation.
            var e = KalivStreamContract.Parse("{\"error\":\"context length exceeded\"}");
            Assert.AreEqual(KalivStreamEventKind.Failure, e.Kind);
            Assert.AreEqual("context length exceeded", e.Info);
        }

        [Test]
        public void TypedErrorWins_OverAnyContentOnTheSameLine()
        {
            var e = KalivStreamContract.Parse(
                "{\"type\":\"error\",\"detail\":\"upstream died\",\"message\":{\"content\":\"ignorer mig\"}}");
            Assert.AreEqual(KalivStreamEventKind.Failure, e.Kind);
            Assert.AreEqual("upstream died", e.Info);
        }

        // --- phase ----------------------------------------------------------------------

        [Test]
        public void PhaseLine_IsAPhase_NotContent()
        {
            // A phase must not count as content: a stream that announced a phase and then
            // died is an answer that never started, not a truncated one.
            var e = KalivStreamContract.Parse("{\"phase\":\"loading_model\"}");
            Assert.AreEqual(KalivStreamEventKind.Phase, e.Kind);
            Assert.AreEqual("loading_model", e.Info);
            Assert.AreEqual("", e.Text);
        }

        // --- what an exhausted stream means ----------------------------------------------

        [Test]
        public void TerminalSeen_IsARealCompletion()
        {
            Assert.IsNull(KalivStreamContract.TerminalFailure(sawTerminal: true, sawContent: true));
            Assert.IsNull(KalivStreamContract.TerminalFailure(sawTerminal: true, sawContent: false));
        }

        [Test]
        public void BodyEndedAfterContent_ReadsAsTruncated()
        {
            // The core rule: a body running out is not completion. A proxy timeout ends the
            // body exactly like a finished answer does.
            var msg = KalivStreamContract.TerminalFailure(sawTerminal: false, sawContent: true);
            Assert.IsNotNull(msg);
            StringAssert.Contains("afbrudt undervejs", msg);
        }

        [Test]
        public void BodyEndedWithoutContent_ReadsAsEmptyStream()
        {
            var msg = KalivStreamContract.TerminalFailure(sawTerminal: false, sawContent: false);
            Assert.IsNotNull(msg);
            StringAssert.Contains("tom stream", msg);
        }

        [Test]
        public void PhaseAloneDoesNotCountAsContent_SoTheFailureIsEmptyNotTruncated()
        {
            // Reading the two pieces together, the way the app does: a phase arrived, then
            // the link dropped. sawContent stays false, so the user is told nothing came
            // back — not that their answer was cut short.
            var e = KalivStreamContract.Parse("{\"phase\":\"loading_model\"}");
            bool sawContent = e.Kind == KalivStreamEventKind.Delta;
            bool sawTerminal = e.Kind == KalivStreamEventKind.Done;

            var msg = KalivStreamContract.TerminalFailure(sawTerminal, sawContent);
            StringAssert.Contains("tom stream", msg);
        }
    }
}
