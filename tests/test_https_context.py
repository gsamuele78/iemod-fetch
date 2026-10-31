"""
One TLS context per process (ADR-0048): building one loads the system's
trust store - on Windows every certificate of the store, parsed while the
GIL is held, 50-240 ms measured on the runner - so a download started from
the wizard froze its window. Built once, shared by every HttpClient, and
built by the wizard before its window is drawn.
"""
import ssl
import urllib.request

import pytest

from iemod_fetch import api, net


@pytest.fixture
def fresh(monkeypatch):
    """No context built yet, and every build counted."""
    monkeypatch.setattr(net, "_HTTPS_CONTEXT", None)
    built = []
    real = ssl.create_default_context

    def counting(*args, **kwargs):
        built.append(1)
        return real(*args, **kwargs)
    monkeypatch.setattr(net.ssl, "create_default_context", counting)
    return built


def _https_handler(client):
    return next(h for h in client._opener.handlers
                if isinstance(h, urllib.request.HTTPSHandler))


def test_every_client_shares_one_context_built_once(fresh):
    first, second = net.HttpClient(), net.HttpClient(allow_http=True)
    assert len(fresh) == 1
    assert _https_handler(first)._context is _https_handler(second)._context
    assert _https_handler(first)._context is net.https_context()


def test_the_shared_context_still_verifies(fresh):
    """Sharing changes when it is built, not what it accepts (ADR-0003)."""
    context = net.https_context()
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert context.minimum_version >= ssl.TLSVersion.TLSv1_2


def test_prepare_https_builds_it_ahead_of_any_run(fresh):
    api.prepare_https()
    assert len(fresh) == 1 and net._HTTPS_CONTEXT is not None
    net.HttpClient()
    assert len(fresh) == 1          # the run finds it built
