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


@pytest.mark.parametrize(
    "response,results,expected",
    [
        (portal.RESPONSE_SUCCESS, {"uri": "file:///tmp/shot.png"}, (portal.CAPTURED, "file:///tmp/shot.png")),
        (portal.RESPONSE_CANCELLED, {}, (portal.CANCELLED, "")),
        (portal.RESPONSE_CANCELLED, {"uri": "file:///tmp/shot.png"}, (portal.CANCELLED, "")),
        (portal.RESPONSE_FAILED, {}, (portal.FAILED, "The screenshot was not taken.")),
        (7, {}, (portal.FAILED, "The screenshot was not taken.")),
    ],
)
def test_response_maps_to_an_outcome(response, results, expected):
    assert portal.interpret_response(response, results) == expected


def test_success_without_a_uri_is_a_failure_not_a_capture():
    """A portal that answers "fine" and hands over nothing must not be treated
    as a capture: the caller would go looking for a file that is not there."""
    assert portal.interpret_response(portal.RESPONSE_SUCCESS, {}) == (
        portal.FAILED,
        "The portal returned no image.",
    )


def test_cancelling_is_distinguishable_from_failing():
    """Callers hide their window for a capture and need it back afterwards, so
    cancellation has to be an outcome of its own rather than silence."""
    cancelled, _ = portal.interpret_response(portal.RESPONSE_CANCELLED, {})
    failed, _ = portal.interpret_response(portal.RESPONSE_FAILED, {})
    assert cancelled == portal.CANCELLED
    assert failed == portal.FAILED
    assert cancelled != failed
