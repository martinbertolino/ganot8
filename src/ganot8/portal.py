"""Taking a screenshot through the XDG desktop portal.

The portal is the only way to capture the screen on Wayland without special
privileges, and it works the same inside and outside a sandbox - which is why
it is used here rather than a compositor-specific call.

The exchange is asynchronous and indirect: calling Screenshot() returns the
object path of a Request, and the answer arrives later as a Response signal on
that path. The path is predictable from the connection's unique name plus a
token we choose, so the signal subscription can be in place before the call is
made and no reply can be missed.
"""

from __future__ import annotations

import logging
import re
from typing import Callable

from . import gi_init  # noqa: F401
from gi.repository import Gio, GLib

log = logging.getLogger(__name__)

PORTAL_BUS = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
SCREENSHOT_IFACE = "org.freedesktop.portal.Screenshot"
REQUEST_IFACE = "org.freedesktop.portal.Request"

#: Portal response codes.
RESPONSE_SUCCESS = 0
RESPONSE_CANCELLED = 1
RESPONSE_FAILED = 2

_token_counter = 0


class PortalError(Exception):
    """Raised when the screenshot portal is unavailable or refuses."""


def _next_token() -> str:
    global _token_counter
    _token_counter += 1
    return f"ganot8{_token_counter}"


def request_path(connection: Gio.DBusConnection, token: str) -> str:
    """The object path the portal will create for our request.

    Derived from our unique bus name with the leading colon dropped and every
    dot turned into an underscore, which is what the portal specification
    prescribes.
    """
    unique_name = connection.get_unique_name() or ""
    sender = re.sub(r"\W", "_", unique_name.lstrip(":"))
    return f"{PORTAL_PATH}/request/{sender}/{token}"


def is_available() -> bool:
    """Whether a screenshot portal is running and answering."""
    try:
        proxy = Gio.DBusProxy.new_for_bus_sync(
            Gio.BusType.SESSION,
            Gio.DBusProxyFlags.DO_NOT_AUTO_START,
            None,
            PORTAL_BUS,
            PORTAL_PATH,
            SCREENSHOT_IFACE,
            None,
        )
    except GLib.Error as error:
        log.info("screenshot portal unavailable: %s", error.message)
        return False
    return proxy.get_cached_property("version") is not None


def take_screenshot(
    on_uri: Callable[[str], None],
    on_error: Callable[[str], None],
    *,
    parent_window: str = "",
    interactive: bool = True,
) -> None:
    """Ask the portal for a screenshot.

    ``interactive`` lets the user pick an area or window - which is almost
    always what is wanted before annotating - and also means the portal shows
    its own consent UI, so no permission is taken silently.
    """
    try:
        connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    except GLib.Error as error:
        on_error(f"Could not reach the session bus: {error.message}")
        return

    token = _next_token()
    path = request_path(connection, token)
    subscription = {"id": 0}

    def on_response(_conn, _sender, _path, _iface, _signal, parameters) -> None:
        if subscription["id"]:
            connection.signal_unsubscribe(subscription["id"])
            subscription["id"] = 0
        response, results = parameters.unpack()
        if response == RESPONSE_CANCELLED:
            return  # the user said no; that is not an error
        if response != RESPONSE_SUCCESS:
            on_error("The screenshot was not taken.")
            return
        uri = results.get("uri")
        if not uri:
            on_error("The portal returned no image.")
            return
        on_uri(uri)

    # Subscribe before calling, so a fast portal cannot answer first.
    subscription["id"] = connection.signal_subscribe(
        PORTAL_BUS,
        REQUEST_IFACE,
        "Response",
        path,
        None,
        Gio.DBusSignalFlags.NO_MATCH_RULE,
        on_response,
    )

    options = {
        "handle_token": GLib.Variant("s", token),
        "interactive": GLib.Variant("b", interactive),
    }

    def called(_source, result) -> None:
        try:
            connection.call_finish(result)
        except GLib.Error as error:
            if subscription["id"]:
                connection.signal_unsubscribe(subscription["id"])
                subscription["id"] = 0
            on_error(f"The screenshot portal refused: {error.message}")

    connection.call(
        PORTAL_BUS,
        PORTAL_PATH,
        SCREENSHOT_IFACE,
        "Screenshot",
        GLib.Variant("(sa{sv})", (parent_window, options)),
        GLib.VariantType("(o)"),
        Gio.DBusCallFlags.NONE,
        -1,
        None,
        called,
    )
