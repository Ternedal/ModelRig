# DC-L16 VisionRig sensor-control successor handoff

**Date:** 27/09-2026  
**Status:** bounded successor qualification  
**production_activation:** false

## Purpose

The original DC-L16 product-integration handoff pins
`backend/internal/httpapi/server.go` to blob
`582b163d7a71a934b43671ddad62a5644df3087e`. That historical artifact remains
unchanged.

This successor handoff authorizes exactly one later source transition for a
separate capability: toggling the desired enabled state of an already-known
VisionRig sensor from the authenticated ModelRig Control Center.

## Exact transition

- path: `backend/internal/httpapi/server.go`
- from: `582b163d7a71a934b43671ddad62a5644df3087e`
- to: `f9b646350c70900ec256387b7a7e544d2de3eb0b`

## Capability boundary

The route is mounted only when
`KALIV_VISIONRIG_SENSOR_CONTROL=1`:

`PATCH /api/v1/control-center/vision/sensors/{sourceID}/enabled`

The backend remains Bearer-authenticated. The request accepts exactly one
boolean `enabled` field. VisionRig must resolve to loopback. The upstream
metadata receipt must match both the requested sensor id and resulting enabled
state before ModelRig returns success.

This handoff grants no generic sensor-metadata mutation, no raw perception or
frame access, no scheduler/tool execution authority, and no production
activation authority.
