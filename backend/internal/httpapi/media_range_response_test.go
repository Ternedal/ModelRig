package httpapi

import (
    "net/http"
    "testing"
)

func TestMediaRangeResponse(t *testing.T) {
    for _, tc := range []struct {
        header string
        size int64
        status int
        start, end int64
        contentRange string
        length int64
    }{
        {"", 100, http.StatusOK, 0, 99, "", 100},
        {"", 0, http.StatusOK, 0, -1, "", 0},
        {"bytes=10-19", 100, http.StatusPartialContent, 10, 19, "bytes 10-19/100", 10},
        {"bytes=-10", 100, http.StatusPartialContent, 90, 99, "bytes 90-99/100", 10},
        {"bytes=-500", 100, http.StatusPartialContent, 0, 99, "bytes 0-99/100", 100},
        {"items=0-1", 100, http.StatusOK, 0, 99, "", 100},
        {"bytes=abc", 100, http.StatusOK, 0, 99, "", 100},
        {"bytes=0-1,4-5", 100, http.StatusOK, 0, 99, "", 100},
        {"bytes=100-", 100, http.StatusRequestedRangeNotSatisfiable, 0, 0, "bytes */100", 0},
        {"bytes=0-0", 0, http.StatusRequestedRangeNotSatisfiable, 0, 0, "bytes */0", 0},
        {"bytes=-0", 100, http.StatusRequestedRangeNotSatisfiable, 0, 0, "bytes */100", 0},
        {"items=0-1", 0, http.StatusOK, 0, -1, "", 0},
    } {
        status, start, end, cr, length, err := mediaRangeResponse(tc.header, tc.size)
        if err != nil || status != tc.status || start != tc.start || end != tc.end || cr != tc.contentRange || length != tc.length {
            t.Errorf("%q size %d: got status=%d start=%d end=%d cr=%q length=%d err=%v; want %+v",
                tc.header, tc.size, status, start, end, cr, length, err, tc)
        }
    }
}

func TestMediaRangeResponseRejectsUnverifiedSize(t *testing.T) {
    for _, header := range []string{"", "bytes=0-1", "bytes=100-", "items=0-1"} {
        status, _, _, cr, _, err := mediaRangeResponse(header, -1)
        if err == nil || status != 0 || cr != "" {
            t.Errorf("negative size leaked response for %q: status=%d cr=%q err=%v", header, status, cr, err)
        }
    }
}
