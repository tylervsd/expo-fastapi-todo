"""Tests cannot inherit account settings or use the real HTTP transport."""

import os

import httpx
import pytest


@pytest.fixture(autouse=True)
def offline_environment(monkeypatch):
    for name in list(os.environ):
        if name.startswith(("IVR_", "TELNYX_")):
            monkeypatch.delenv(name)

    async def no_network(self, request):
        raise AssertionError("Offline test attempted real outbound HTTP")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", no_network)
