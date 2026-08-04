"""Deprecated internal shim for retained publisher-authorization v1 artifacts.

The implementation lives in ``kaliv_dev_control._compatibility_v1``. Public
consumers must use ``publisher_authorization`` and its Ed25519/v2 surface.
"""
from ._compatibility_v1.publisher_authorization import *  # noqa: F403
