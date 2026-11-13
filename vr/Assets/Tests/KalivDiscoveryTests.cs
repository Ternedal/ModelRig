using System.Net;
using NUnit.Framework;

namespace Kaliv.VR.Tests
{
    public sealed class KalivDiscoveryTests
    {
        [Test]
        public void A24_ProbesEveryNeighbourButNotItself()
        {
            var t = KalivRigDiscovery.ScanTargets(IPAddress.Parse("192.168.1.42"), IPAddress.Parse("255.255.255.0"));
            Assert.AreEqual(253, t.Count);                 // 254 hosts minus the headset
            CollectionAssert.DoesNotContain(t, "192.168.1.42");
            CollectionAssert.DoesNotContain(t, "192.168.1.0");     // network
            CollectionAssert.DoesNotContain(t, "192.168.1.255");   // broadcast
            CollectionAssert.Contains(t, "192.168.1.1");
            CollectionAssert.Contains(t, "192.168.1.254");
        }

        [Test]
        public void AWideNetwork_IsCappedAtThe24AroundTheHeadset()
        {
            // A /16 would be 65 534 requests; only the headset's own /24 is scanned.
            var t = KalivRigDiscovery.ScanTargets(IPAddress.Parse("10.0.7.9"), IPAddress.Parse("255.255.0.0"));
            Assert.AreEqual(253, t.Count);
            Assert.IsTrue(t.TrueForAll(a => a.StartsWith("10.0.7.")));
        }

        [Test]
        public void ANarrowNetwork_StaysNarrow()
        {
            var t = KalivRigDiscovery.ScanTargets(IPAddress.Parse("192.168.1.130"), IPAddress.Parse("255.255.255.128"));
            Assert.AreEqual(125, t.Count);                 // .129–.254 minus the headset
            Assert.IsTrue(t.TrueForAll(a => int.Parse(a.Split('.')[3]) >= 129));
        }

        [Test]
        public void AMissingMask_AssumesA24()
        {
            // Android's IL2CPP does not always implement IPv4Mask.
            Assert.AreEqual(253, KalivRigDiscovery.ScanTargets(IPAddress.Parse("192.168.0.5"), null).Count);
        }

        [Test]
        public void PointToPointLinks_HaveNoNeighboursToScan()
        {
            Assert.IsEmpty(KalivRigDiscovery.ScanTargets(IPAddress.Parse("10.1.1.1"), IPAddress.Parse("255.255.255.255")));
            Assert.IsEmpty(KalivRigDiscovery.ScanTargets(IPAddress.Parse("10.1.1.1"), IPAddress.Parse("255.255.255.254")));
            Assert.IsEmpty(KalivRigDiscovery.ScanTargets(IPAddress.Parse("::1"), null));
        }

        [Test]
        public void OnlyTheBackendsOwnHealthAnswerCounts()
        {
            Assert.IsTrue(KalivRigDiscovery.IsModelRig("{\"status\":\"ok\",\"service\":\"modelrig-server\",\"version\":\"2.0.19\"}", out var v));
            Assert.AreEqual("2.0.19", v);
            // A router admin page, another JSON service, or the worker must never be mistaken for it.
            Assert.IsFalse(KalivRigDiscovery.IsModelRig("<html>router</html>", out _));
            Assert.IsFalse(KalivRigDiscovery.IsModelRig("{\"status\":\"ok\"}", out _));
            Assert.IsFalse(KalivRigDiscovery.IsModelRig("{\"service\":\"stash-skyplayer-companion\"}", out _));
            Assert.IsFalse(KalivRigDiscovery.IsModelRig(null, out _));
        }
    }
}
