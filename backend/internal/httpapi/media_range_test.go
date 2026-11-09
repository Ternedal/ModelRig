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

func TestMediaRangeHeaders(t *testing.T) {
    for _, tc := range []struct {
        header string
        size int64
        status int
        contentRange string
        length int64
    }{
        {"", 0, 200, "", 0},
        {"", 100, 200, "", 100},
        {"bytes=0-9", 100, 206, "bytes 0-9/100", 10},
        {"bytes=90-999", 100, 206, "bytes 90-99/100", 10},
        {"bytes=0-", 1, 206, "bytes 0-0/1", 1},
    } {
        start, end, partial, err := mediaByteRange(tc.header, tc.size)
        if err != nil { t.Fatal(err) }
        status, contentRange, length, err := mediaRangeHeaders(start, end, tc.size, partial)
        if err != nil || status != tc.status || contentRange != tc.contentRange || length != tc.length {
            t.Fatalf("%q: status=%d range=%q length=%d err=%v", tc.header, status, contentRange, length, err)
        }
    }
}

func TestMediaRangeHeadersRejectsInvalidBounds(t *testing.T) {
    for _, tc := range []struct { start, end, size int64; partial bool }{
        {-1, 0, 10, true},
        {0, 10, 10, true},
        {2, 1, 10, true},
        {1, 9, 10, false},
        {0, -1, 0, true},
        {0, 0, 0, false},
        {0, 0, -1, false},
    } {
        if _, _, _, err := mediaRangeHeaders(tc.start, tc.end, tc.size, tc.partial); err == nil {
            t.Fatalf("accepted invalid metadata: %+v", tc)
        }
    }
}

func TestMediaUnsatisfiedContentRange(t *testing.T) {
    for _, tc := range []struct { size int64; want string }{
        {0, "bytes */0"},
        {1, "bytes */1"},
        {100, "bytes */100"},
        {9223372036854775807, "bytes */9223372036854775807"},
    } {
        got, err := mediaUnsatisfiedContentRange(tc.size)
        if err != nil || got != tc.want {
            t.Fatalf("size %d: got %q err %v", tc.size, got, err)
        }
    }
    if _, err := mediaUnsatisfiedContentRange(-1); err == nil {
        t.Fatal("negative asset size accepted")
    }
}
