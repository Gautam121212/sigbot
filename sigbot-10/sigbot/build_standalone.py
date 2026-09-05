"""Two ways to get the app onto your phone.

`build_standalone()` produces one HTML file with the data baked in. No server,
no network, no firewall, no router settings. Send it to yourself however you
already send files and open it. This is the route that cannot fail on a network
problem, because it does not use the network.

`serve()` runs the LAN server and prints the address that actually works,
because "same Wi-Fi" is necessary and not sufficient. Four things commonly stop
a phone reaching a laptop on the same network:

  1. The laptop firewall drops inbound connections on that port. This is the
     usual cause on Windows, and macOS asks once and remembers "deny" if you
     dismissed the prompt.
  2. The router has client isolation on, so devices cannot see each other.
     Standard on guest networks and on many ISP-supplied routers by default.
  3. The phone is on mobile data, or on a different band the router treats as a
     separate network.
  4. A VPN on either device routes traffic away from the LAN.

One more thing worth knowing: over plain HTTP on a LAN address, iOS will not
register a service worker. The app still loads and works — you just do not get
offline caching until it is served over HTTPS. "Add to Home Screen" still works.
"""
from __future__ import annotations

import json
import socket
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent / "app"
SLOT_OPEN = '<script id="inline-data" type="application/json">'
SLOT_CLOSE = "</script>"


def lan_addresses() -> list[str]:
    """Every non-loopback IPv4 address this machine answers on."""
    found: set[str] = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))     # no packet is sent
        found.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if isinstance(ip, str) and not ip.startswith("127."):
                found.add(ip)
    except OSError:
        pass
    return sorted(found)


def build_standalone(app_dir: Path = APP_DIR,
                     data_file: str = "data.json",
                     out_name: str = "sigbot-standalone.html") -> Path:
    """Bake data.json into index.html so the page works from file://.

    Browsers block fetch() for local files, which is why opening index.html
    directly shows an empty app. Inlining the JSON removes the fetch entirely.
    """
    index = app_dir / "index.html"
    data = app_dir / data_file
    if not index.exists():
        raise FileNotFoundError(f"{index} not found")
    if not data.exists():
        raise FileNotFoundError(
            f"{data} not found — run `python -m sigbot.export_app {data}` first"
        )

    html = index.read_text(encoding="utf-8")
    if SLOT_OPEN not in html:
        raise ValueError("index.html has no inline-data slot; it is out of date")

    payload = json.dumps(json.loads(data.read_text(encoding="utf-8")))
    # </script> inside JSON would close the tag early and break the page.
    payload = payload.replace("</", "<\\/")

    start = html.index(SLOT_OPEN) + len(SLOT_OPEN)
    end = html.index(SLOT_CLOSE, start)
    out = app_dir / out_name
    out.write_text(html[:start] + payload + html[end:], encoding="utf-8")
    return out


def serve(port: int = 8080, app_dir: Path = APP_DIR) -> None:
    import functools
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(app_dir))
    addrs = lan_addresses()

    print(f"Serving {app_dir} on port {port}\n")
    print("  On this machine:  http://localhost:%d" % port)
    if addrs:
        print("  From your phone:")
        for ip in addrs:
            print(f"                    http://{ip}:{port}")
    else:
        print("  No LAN address detected — the standalone file is the better route.")
    print("\nIf the phone cannot reach it, in this order:")
    print("  1. allow inbound connections for python on this port in the firewall")
    print("  2. turn off client isolation / AP isolation on the router")
    print("  3. check the phone is on Wi-Fi, not mobile data, and on the same band")
    print("  4. turn off any VPN on either device")
    print("\nOr skip the network entirely:")
    print("  python -m sigbot.build_standalone")
    print("  then send app/sigbot-standalone.html to your phone and open it.\n")

    # Bind on every interface explicitly: a loopback-only bind is invisible to
    # the phone even when everything else is configured correctly.
    ThreadingHTTPServer(("0.0.0.0", port), handler).serve_forever()


if __name__ == "__main__":
    import sys

    if "--serve" in sys.argv:
        idx = sys.argv.index("--serve")
        port = int(sys.argv[idx + 1]) if len(sys.argv) > idx + 1 else 8080
        serve(port)
    else:
        out = build_standalone()
        size = out.stat().st_size / 1024
        print(f"wrote {out}  ({size:.0f} KB, self-contained)")
        print("Send that one file to your phone and open it. No server needed.")
