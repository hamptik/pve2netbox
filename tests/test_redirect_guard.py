"""Tests for the redirect guard on the NetBox HTTP session.

A silently followed redirect downgrades writes to GET (http->https 301 in
front of a NetBox made every POST/PATCH a no-op). The adapter must raise a
clear RuntimeError instead, for every method — the configured NB_API_URL is
expected to be the final URL.
"""

import pytest

from pve2netbox import _raise_if_redirect


class FakeRequest:
    def __init__(self, method):
        self.method = method


class FakeResponse:
    def __init__(self, status_code, location=None, method='POST', url='http://netbox/api/extras/tags/'):
        self.status_code = status_code
        self.headers = {'Location': location} if location else {}
        self.request = FakeRequest(method)
        self.url = url


@pytest.mark.parametrize('status', [301, 302, 303, 307, 308])
def test_redirect_raises_for_all_redirect_codes(status):
    with pytest.raises(RuntimeError) as exc:
        _raise_if_redirect(FakeResponse(status, location='https://netbox/api/extras/tags/'))
    msg = str(exc.value)
    assert str(status) in msg
    assert 'https://netbox/api/extras/tags/' in msg
    assert 'NB_API_URL' in msg


@pytest.mark.parametrize('status', [200, 201, 204, 400, 401, 404, 429, 500, 503])
def test_non_redirect_statuses_pass_through(status):
    # Must not raise.
    _raise_if_redirect(FakeResponse(status))


def test_redirect_without_location_still_raises():
    with pytest.raises(RuntimeError):
        _raise_if_redirect(FakeResponse(301, location=None))


def test_get_redirect_also_raises():
    """Even a GET redirect means misconfigured URL — fail loudly."""
    with pytest.raises(RuntimeError):
        _raise_if_redirect(FakeResponse(301, location='https://netbox/', method='GET'))
