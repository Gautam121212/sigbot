# Sigbot app

An installable PWA. No build step, no npm, no bundler — `index.html` is the app.

## Getting it on your phone

### Route 0 — the one that works on iPhone

```bash
python -m sigbot.export_app app/data.json
python -m sigbot.build_static
```

Writes `app/sigbot-report.html`. Send it to yourself and open it.

**Why this exists.** Opening `sigbot-standalone.html` from Files on an iPhone
shows the word "Sigbot" and nothing else. The JavaScript is fine — `node
--check` passes — but iOS previews HTML attachments in Quick Look, which
renders markup and does not run scripts. Every element except the brand text
was written by JS into an empty container, so the preview showed one word.

`sigbot-report.html` has **no scripts at all**. The numbers are in the markup,
drill-down uses `<details>`, and it needs no server, no network and no
JavaScript. It opens in Quick Look, in Mail, in any browser, offline, and it
prints. 9 KB.

Trade-off: it is a static snapshot with no tab navigation. Rebuild to refresh.

### Route 1 — one file, no network (use this if the server route failed)

```bash
python -m sigbot.export_app app/data.json
python -m sigbot.build_standalone
```

That writes `app/sigbot-standalone.html` with the data baked into the page.
Send it to yourself however you already send files — WhatsApp, email, AirDrop,
Google Drive — and open it. No server, no Wi-Fi, no firewall, no router
settings. It cannot fail on a network problem because it does not use the
network.

Trade-off: it is a snapshot. Rebuild and resend when you want fresh numbers.

### Route 2 — LAN server (live, refreshes on reload)

```bash
python -m sigbot.build_standalone --serve 8080
```

This binds every interface and prints the address your phone should use. Plain
`python -m http.server` also works, but it will not tell you which of your
addresses is the right one.

**"Same Wi-Fi" is necessary, not sufficient.** In the order worth checking:

1. **Laptop firewall.** The usual cause on Windows — inbound connections to
   python on that port are blocked by default. macOS asks once, and remembers
   "deny" if you dismissed the prompt.
2. **Client isolation** (sometimes "AP isolation") on the router stops devices
   seeing each other. On by default on many ISP-supplied routers and on every
   guest network.
3. **Phone actually on Wi-Fi**, not mobile data — and on the same band. Some
   routers put 2.4GHz and 5GHz on separate networks.
4. **VPN** on either device routes traffic away from the LAN.

Test 1 and 2 quickly: open `http://<laptop-ip>:8080` in the laptop's own
browser. If that works but the phone does not, it is the firewall or the router,
not the app.

## Install to your home screen

- **Android / Chrome** — menu → "Install app" / "Add to Home screen"
- **iPhone / Safari** — Share → "Add to Home Screen"

Opens fullscreen with its own icon after that.

One caveat on iOS: over plain HTTP on a LAN address, Safari will not register
the service worker, so you lose offline caching. The app still loads and Add to
Home Screen still works. Offline caching needs HTTPS — a Cloudflare Tunnel or
ngrok gives you that free if you want it.

## Why not the App Store

Three blockers, in order of how hard they are to remove:

1. **$99/year** Apple Developer Program. That breaks "zero cost" before a line
   of code ships.
2. **A wrapper build.** A web app cannot be submitted as-is. It needs Capacitor
   or React Native, plus a Mac running Xcode.
3. **Review.** Apple scrutinises apps that produce investment signals. Expect
   questions about who is giving advice and on what authority. This app rates
   evidence rather than recommending trades, which helps, but it is still the
   category reviewers look at hardest.

A PWA skips all three, installs in about ten seconds, and updates when you
regenerate `data.json`. Revisit the store only if you ever want to charge for it.

## Keeping it current

```cron
0 20 * * *  cd /path/to/sigbot && python -m sigbot.runner daily && python -m sigbot.export_app app/data.json
```

The app renders `data.json` and nothing else, so it cannot display a number the
backend did not produce. `data.json` is fetched network-first — a cached
snapshot presented as current would be exactly the stale-but-confident reading
this project exists to prevent.

## Files

| File | What it is |
|---|---|
| `index.html` | The whole app: markup, styles, logic |
| `manifest.webmanifest` | Name, icon, colours for installation |
| `sw.js` | Offline shell; data stays network-first |
| `icon.svg` | App icon |
| `data.json` | Written by `sigbot.export_app` |
| `sigbot-standalone.html` | Portable single file with JS. Built by `sigbot.build_standalone` |
| `sigbot-report.html` | **No-JavaScript report.** Works in iOS Files preview. Built by `sigbot.build_static` |
