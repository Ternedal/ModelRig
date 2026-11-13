package httpapi

import (
    "errors"
    "strconv"
    "strings"
)

// Distinguish a Range field that must be ignored (serve 200) from an
// unsatisfiable valid byte range (serve 416 after owner authorization).
var (
    errRangeIgnore = errors.New("ignore Range and serve full representation")
    errRangeUnsatisfiable = errors.New("unsatisfiable byte range")
)

// mediaByteRange parses a single byte range without file-sized allocations.
// Unknown units, malformed syntax and multiple ranges are ignored (200).
// Suffix ranges are supported. Only valid unsatisfiable ranges return 416.
func mediaByteRange(header string, size int64) (start, end int64, partial bool, err error) {
    if size < 0 { return 0, 0, false, errors.New("invalid asset size") }
    if header == "" {
        if size == 0 { return 0, -1, false, nil }
        return 0, size - 1, false, nil
    }
    if len(header) > 128 || !strings.HasPrefix(header, "bytes=") {
        return 0, 0, false, errRangeIgnore
    }
    spec := strings.TrimPrefix(header, "bytes=")
    if strings.Contains(spec, ",") || strings.Count(spec, "-") != 1 {
        return 0, 0, false, errRangeIgnore
    }
    parts := strings.SplitN(spec, "-", 2)
    if parts[0] == "" && parts[1] == "" { return 0, 0, false, errRangeIgnore }
    for _, part := range parts {
        for _, ch := range part {
            if ch < '0' || ch > '9' { return 0, 0, false, errRangeIgnore }
        }
    }
    if parts[0] == "" {
        suffix, parseErr := strconv.ParseInt(parts[1], 10, 64)
        if parseErr != nil { return 0, 0, false, errRangeIgnore }
        if suffix == 0 || size == 0 { return 0, 0, false, errRangeUnsatisfiable }
        if suffix >= size { return 0, size - 1, true, nil }
        return size - suffix, size - 1, true, nil
    }
    start, err = strconv.ParseInt(parts[0], 10, 64)
    if err != nil { return 0, 0, false, errRangeIgnore }
    if start >= size { return 0, 0, false, errRangeUnsatisfiable }
    if parts[1] == "" { return start, size - 1, true, nil }
    end, err = strconv.ParseInt(parts[1], 10, 64)
    if err != nil { return 0, 0, false, errRangeIgnore }
    if end < start { return 0, 0, false, errRangeIgnore }
    if end >= size { end = size - 1 }
    return start, end, true, nil
}

// mediaRangeHeaders returns the status and exact byte metadata for a verified
// asset descriptor. Call only after authorization and mediaByteRange succeed.
// The caller must stream from the same opened descriptor, never reopen by path.
func mediaRangeHeaders(start, end, size int64, partial bool) (int, string, int64, error) {
    if size < 0 || start < 0 || (size == 0 && (end != -1 || partial)) ||
        (size > 0 && (end < start || end >= size)) ||
        (!partial && size > 0 && (start != 0 || end != size-1)) {
        return 0, "", 0, errors.New("invalid verified media range")
    }
    if size == 0 {
        if start != 0 { return 0, "", 0, errors.New("invalid empty media range") }
        return 200, "", 0, nil
    }
    length := end - start + 1
    if partial {
        return 206, "bytes " + strconv.FormatInt(start, 10) + "-" +
            strconv.FormatInt(end, 10) + "/" + strconv.FormatInt(size, 10), length, nil
    }
    return 200, "", length, nil
}

 
// mediaUnsatisfiedContentRange formats the RFC 9110 unsatisfied range value.
// A 416 response must not reveal an asset's size until the caller has been
// authenticated and authorized to read that exact completed asset.
func mediaUnsatisfiedContentRange(size int64) (string, error) {
    if size < 0 {
        return "", errors.New("invalid verified asset size")
    }
    return "bytes */" + strconv.FormatInt(size, 10), nil
}
