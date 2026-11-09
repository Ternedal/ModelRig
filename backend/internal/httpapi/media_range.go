package httpapi

import (
    "errors"
    "strconv"
    "strings"
)

// mediaByteRange parses one HTTP byte range without allocating file-sized buffers.
// It refuses multi-range and suffix ranges until the streaming adapter supports
// them explicitly; callers should answer 416 with Content-Range: bytes */size.
func mediaByteRange(header string, size int64) (start, end int64, partial bool, err error) {
    if size < 0 { return 0, 0, false, errors.New("invalid asset size") }
    if header == "" {
        if size == 0 { return 0, -1, false, nil }
        return 0, size - 1, false, nil
    }
    if size == 0 || len(header) > 128 || !strings.HasPrefix(header, "bytes=") {
        return 0, 0, false, errors.New("invalid byte range")
    }
    spec := strings.TrimPrefix(header, "bytes=")
    if strings.Contains(spec, ",") || strings.Count(spec, "-") != 1 {
        return 0, 0, false, errors.New("unsupported byte range")
    }
    parts := strings.SplitN(spec, "-", 2)
    if parts[0] == "" { return 0, 0, false, errors.New("suffix range unsupported") }
    start, err = strconv.ParseInt(parts[0], 10, 64)
    if err != nil || start < 0 || start >= size { return 0, 0, false, errors.New("invalid range start") }
    if parts[1] == "" { return start, size - 1, true, nil }
    end, err = strconv.ParseInt(parts[1], 10, 64)
    if err != nil || end < start { return 0, 0, false, errors.New("invalid range end") }
    if end >= size { end = size - 1 }
    return start, end, true, nil
}
