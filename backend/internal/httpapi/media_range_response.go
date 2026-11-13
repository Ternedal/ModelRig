package httpapi

import (
    "errors"
    "net/http"
)

// mediaRangeResponse resolves a request Range header against an already
// authorized, verified asset size. Callers must authenticate and verify
// ownership before calling: a 416 response exposes the asset's size.
// A 200/206 result describes bytes to stream from the same verified open file.
// For 416, length is zero and start/end must not be used.
func mediaRangeResponse(header string, size int64) (status int, start int64, end int64, contentRange string, length int64, err error) {
    start, end, partial, rangeErr := mediaByteRange(header, size)
    if errors.Is(rangeErr, errRangeIgnore) {
        start, end, partial, rangeErr = mediaByteRange("", size)
    }
    if errors.Is(rangeErr, errRangeUnsatisfiable) {
        contentRange, err = mediaUnsatisfiedContentRange(size)
        if err != nil {
            return 0, 0, 0, "", 0, err
        }
        return http.StatusRequestedRangeNotSatisfiable, 0, 0, contentRange, 0, nil
    }
    if rangeErr != nil {
        return 0, 0, 0, "", 0, rangeErr
    }
    status, contentRange, length, err = mediaRangeHeaders(start, end, size, partial)
    if err != nil {
        return 0, 0, 0, "", 0, err
    }
    return status, start, end, contentRange, length, nil
}
