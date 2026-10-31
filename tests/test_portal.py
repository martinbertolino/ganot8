"""The screenshot portal exchange.

Taking an actual screenshot needs a person to approve it, so what is checked
here is the part that can be wrong without anyone noticing: the object path the
response will arrive on.
"""

from __future__ import annotations

import pytest

from ganot8 import portal


class FakeConnection:
    def __init__(self, name):
        self._name = name

    def get_unique_name(self):
        return self._name


@pytest.mark.parametrize(
    "unique_name,expected",
    [
        (":1.634", "/org/freedesktop/portal/desktop/request/1_634/tok"),
        (":1.2", "/org/freedesktop/portal/desktop/request/1_2/tok"),
        (":12.345", "/org/freedesktop/portal/desktop/request/12_345/tok"),
    ],
)
def test_request_path_follows_the_portal_specification(unique_name, expected):
    """Leading colon dropped, dots to underscores - get this wrong and the
    response signal arrives on a path nobody is listening to."""
    assert portal.request_path(FakeConnection(unique_name), "tok") == expected


def test_request_path_survives_a_missing_bus_name():
    assert portal.request_path(FakeConnection(None), "tok").endswith("/tok")


def test_tokens_are_unique():
    """Two captures in flight at once must not share a response path."""
    tokens = {portal._next_token() for _ in range(20)}
    assert len(tokens) == 20


def test_response_codes_match_the_specification():
    assert (portal.RESPONSE_SUCCESS, portal.RESPONSE_CANCELLED, portal.RESPONSE_FAILED) == (0, 1, 2)
