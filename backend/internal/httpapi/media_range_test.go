package httpapi

import "testing"

func TestMediaByteRange(t *testing.T) {
    cases := []struct {
        header string
        size int64
        start, end int64
        partial bool
    }{
        {"", 100, 0, 99, false},
        {"", 0, 0, -1, false},
        {"bytes=0-9", 100, 0, 9, true},
        {"bytes=50-", 100, 50, 99, true},
        {"bytes=90-999", 100, 90, 99, true},
        {"bytes=0-0", 1, 0, 0, true},
    }
    for _, c := range cases {
        a, b, partial, err := mediaByteRange(c.header, c.size)
        if err != nil || a != c.start || b != c.end || partial != c.partial {
            t.Fatalf("%q size %d: got %d-%d partial=%v err=%v", c.header, c.size, a, b, partial, err)
        }
    }
}
func TestMediaByteRangeRefusesUnsafe(t *testing.T) {
    for _, c := range []struct{ header string; size int64 }{
        {"bytes=0-1,4-5", 100},
        {"bytes=-10", 100},
        {"bytes=100-", 100},
        {"bytes=9-8", 100},
        {"bytes=abc-def", 100},
        {"bytes=0-0", 0},
        {"bytes=0-0", -1},
        {"bytes=+1-2", 100},
        {"bytes=0--1", 100},
        {"bytes=0-999999999999999999999999", 100},
        {"items=0-1", 100},
    } {
        if _, _, _, err := mediaByteRange(c.header, c.size); err == nil {
            t.Fatalf("accepted invalid range %q size %d", c.header, c.size)
        }
    }
}
