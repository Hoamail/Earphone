#!/usr/bin/env python3
"""
yt_ad.py - skip the ad in the YouTube tab that is currently playing.

No extension, no Electron, no pip. Talks Chrome DevTools Protocol (CDP) to a
browser you launched with --remote-debugging-port, asks the page whether an ad is
showing, and acts on it:

  1. skip button present  -> click it (works on skippable ads)
  2. otherwise            -> seek the ad video to its end (kills the remainder)

Works with Edge, Chrome, Chromium, Brave - anything Chromium-based.

Launch the browser once with debugging on (use a separate profile so your real
one is untouched and unlocked):

    microsoft-edge --remote-debugging-port=9222 --user-data-dir=$HOME/.config/yt-ad-prof
    # or: google-chrome --remote-debugging-port=9222 --user-data-dir=...

Then:

    python3 yt_ad.py                 # skip the ad now
    python3 yt_ad.py --loop 1.5      # keep watching; skip every ad as it starts
    python3 yt_ad.py --status        # only report what the tab is doing
    python3 yt_ad.py --self-test     # verify the whole path on a fake ad page
"""

import argparse
import base64
import json
import os
import socket
import struct
import sys
import time
import urllib.request

AD_JS = r"""
(() => {
  const player = document.querySelector('.html5-video-player');
  const ad = !!document.querySelector('.ad-showing')
          || (player ? player.classList.contains('ad-showing') : false);
  const v = document.querySelector('video');
  const out = {ad: !!ad, url: location.href};
  if (!v) { out.state = 'no-video'; return out; }
  out.paused = v.paused;
  out.t = Math.round(v.currentTime);
  out.dur = isFinite(v.duration) ? Math.round(v.duration) : null;
  if (!ad) { out.state = 'content'; return out; }
  const btn = document.querySelector(
    '.ytp-skip-ad-button, .ytp-ad-skip-button, .ytp-ad-skip-button-modern, .ytp-ad-skip-button-slot button');
  if (btn && btn.offsetParent !== null) {
    btn.click();
    out.state = 'skipped-button';
    return out;
  }
  if (isFinite(v.duration) && v.duration > 0) {
    v.currentTime = v.duration;
    if (v.paused) { v.play().catch(() => {}); }
    out.state = 'seeked-end';
    out.dur = Math.round(v.duration);
    return out;
  }
  out.state = 'wait';
  return out;
})()
"""


# ------------------------------------------------------------------ websocket
class WS:
    """Just enough RFC 6455 for CDP: text frames, no extensions."""

    def __init__(self, url, timeout=5.0):
        assert url.startswith("ws://"), url
        rest = url[5:]
        hostport, _, path = rest.partition("/")
        host, _, port = hostport.partition(":")
        self.sock = socket.create_connection((host, int(port or 80)), timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (f"GET /{path} HTTP/1.1\r\nHost: {hostport}\r\nUpgrade: websocket\r\n"
               f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
               "Sec-WebSocket-Version: 13\r\n\r\n")
        self.sock.sendall(req.encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise OSError("handshake closed")
            head += chunk
        if b"101" not in head.split(b"\r\n")[0]:
            raise OSError("websocket upgrade refused: " + head.split(b"\r\n")[0].decode())
        self._id = 0

    def _frame(self, payload: bytes, opcode=0x1):
        mask = os.urandom(4)
        n = len(payload)
        hdr = bytes([0x80 | opcode])
        if n < 126:
            hdr += bytes([0x80 | n])
        elif n < 65536:
            hdr += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            hdr += bytes([0x80 | 127]) + struct.pack(">Q", n)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(hdr + mask + masked)

    def _read(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise OSError("socket closed")
            buf += chunk
        return buf

    def recv(self):
        b1, b2 = self._read(2)
        opcode = b1 & 0x0F
        n = b2 & 0x7F
        if n == 126:
            n = struct.unpack(">H", self._read(2))[0]
        elif n == 127:
            n = struct.unpack(">Q", self._read(8))[0]
        mask = self._read(4) if b2 & 0x80 else None
        data = self._read(n) if n else b""
        if mask:
            data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        if opcode == 0x9:                       # ping -> pong
            self._frame(data, 0x9A & 0x0F | 0xA0)
            return self.recv()
        if opcode == 0x8:
            raise OSError("server closed")
        return data.decode("utf-8", "replace")

    def call(self, method, params=None):
        self._id += 1
        msg = {"id": self._id, "method": method}
        if params:
            msg["params"] = params
        self._frame(json.dumps(msg).encode())
        while True:
            data = self.recv()
            if not data:
                continue
            try:
                obj = json.loads(data)
            except ValueError:
                continue
            if obj.get("id") == self._id:
                if "error" in obj:
                    raise RuntimeError(obj["error"])
                return obj.get("result", {})


# --------------------------------------------------------------------- targets
def http_json(host, port, path):
    with urllib.request.urlopen(f"http://{host}:{port}{path}", timeout=5) as r:
        return json.loads(r.read().decode() or "{}")


def find_target(host, port, match):
    tabs = http_json(host, port, "/json/list")
    pages = [t for t in tabs if t.get("type") == "page"]
    for t in pages:
        if match in t.get("url", ""):
            return t
    return pages[0] if pages else None


def evaluate(tab, js):
    ws = WS(tab["webSocketDebuggerUrl"])
    try:
        res = ws.call("Runtime.evaluate",
                      {"expression": js, "returnByValue": True, "awaitPromise": True})
    finally:
        ws.sock.close()
    if "exceptionDetails" in res:
        raise RuntimeError(res["exceptionDetails"])
    return res.get("result", {}).get("value")


OBSERVER_JS = r"""
(() => {
  if (window.__ytad_installed) return 'already';
  window.__ytad = {count: 0, log: []};
  const t0 = performance.now();
  const act = () => {
    const player = document.querySelector('.html5-video-player');
    const ad = !!document.querySelector('.ad-showing')
            || (player ? player.classList.contains('ad-showing') : false);
    if (!ad) return;
    const v = document.querySelector('video');
    const btn = document.querySelector(
      '.ytp-skip-ad-button, .ytp-ad-skip-button, .ytp-ad-skip-button-modern, .ytp-ad-skip-button-slot button');
    let how = null;
    if (btn && btn.offsetParent !== null) { btn.click(); how = 'button'; }
    else if (v && isFinite(v.duration) && v.duration > 0) {
      v.currentTime = v.duration;
      if (v.paused) { v.play().catch(() => {}); }
      how = 'seek';
    }
    if (how) {
      window.__ytad.count++;
      window.__ytad.log.push({t: Math.round(performance.now() - t0), how: how,
                              dur: v && isFinite(v.duration) ? Math.round(v.duration) : null});
    }
  };
  new MutationObserver(act).observe(document.documentElement, {
    subtree: true, childList: true, attributes: true, attributeFilter: ['class']});
  window.__ytad_act = act;
  window.__ytad_installed = true;
  act();
  return 'installed';
})()
"""

STATS_JS = r"""
(() => {
  if (!window.__ytad) return {installed: false};
  return {installed: true, count: window.__ytad.count, log: window.__ytad.log.slice(-20)};
})()
"""


# ------------------------------------------------------------------ self-test
FAKE_AD = """<!doctype html><html><body>
<div class="html5-video-player ad-showing" id="p">
  <video id="v" duration="NaN"></video>
  <button id="skip" class="ytp-skip-ad-button"
    onclick="window.__clicked=(window.__clicked||0)+1; document.getElementById('p').classList.remove('ad-showing')">
    Skip Ad
  </button>
</div>
</body></html>
"""


def open_fake(host, port, path):
    req = urllib.request.Request(
        f"http://{host}:{port}/json/new?file://{path}", method="PUT")
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read().decode())


def close_tab(host, port, tab):
    try:
        urllib.request.urlopen(
            urllib.request.Request(f"http://{host}:{port}/json/close/{tab['id']}",
                                   method="PUT"), timeout=5).read()
    except OSError:
        pass


def self_test(host, port):
    path = "/tmp/yt_ad_fake.html"
    with open(path, "w", encoding="utf-8") as f:
        f.write(FAKE_AD)
    ok = True
    try:
        # 1. one-shot path
        tab = open_fake(host, port, path)
        time.sleep(0.5)
        before = evaluate(tab, AD_JS)
        after = evaluate(tab, AD_JS)
        clicked = evaluate(tab, "window.__clicked >= 1")
        print("one-shot before:", before)
        print("one-shot after :", after)
        ok &= before.get("state") == "skipped-button" and after.get("ad") is False and clicked is True
        close_tab(host, port, tab)

        # 2. observer path: must fire without any polling
        tab = open_fake(host, port, path)
        time.sleep(0.5)
        print("observer install:", evaluate(tab, OBSERVER_JS))
        time.sleep(0.5)
        stats = evaluate(tab, STATS_JS)
        print("observer stats  :", stats)
        ok &= stats.get("installed") is True and stats.get("count", 0) >= 1
        ok &= stats.get("log", [{}])[-1].get("how") == "button"
        close_tab(host, port, tab)
    finally:
        os.unlink(path)

    print("\nSELF-TEST", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description="skip a YouTube ad over CDP")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9222)
    ap.add_argument("--match", default="youtube.com", help="substring of the tab URL")
    ap.add_argument("--loop", type=float, default=0.5, metavar="SECONDS",
                    help="poll interval when not using --install (default 0.5)")
    ap.add_argument("--install", action="store_true",
                    help="inject a mutation observer: clicks instantly, no polling")
    ap.add_argument("--watch", action="store_true",
                    help="keep the observer installed across reloads (long-running)")
    ap.add_argument("--stats", action="store_true", help="show what was skipped so far")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        return self_test(args.host, args.port)

    try:
        tab = find_target(args.host, args.port, args.match)
    except OSError as e:
        sys.exit(f"no browser on port {args.port} ({e}). Start it with --remote-debugging-port.")
    if not tab:
        sys.exit("no page target found")

    if args.stats:
        print(json.dumps(evaluate(tab, STATS_JS), ensure_ascii=False, indent=1))
        return 0

    if args.install:
        print("observer:", evaluate(tab, OBSERVER_JS))
        time.sleep(0.3)
        print("stats   :", json.dumps(evaluate(tab, STATS_JS), ensure_ascii=False))
        return 0

    if args.watch:
        print(f"watching {tab['url']} - observer reinstalled after every load")
        while True:
            try:
                state = evaluate(tab, STATS_JS)
                if not state.get("installed"):
                    print(f"{time.strftime('%H:%M:%S')}  (re)installing observer")
                    evaluate(tab, OBSERVER_JS)
                else:
                    last = state.get("log") or []
                    if last:
                        print(f"{time.strftime('%H:%M:%S')}  skipped {state['count']} "
                              f"total, last: {last[-1]}")
                        evaluate(tab, "window.__ytad.log = window.__ytad.log.slice(-5)")
            except (OSError, RuntimeError):
                tab = find_target(args.host, args.port, args.match)
                if not tab:
                    print("tab went away")
                    return 1
            time.sleep(5.0)

    if not args.loop:
        res = evaluate(tab, AD_JS)
        print(json.dumps(res, ensure_ascii=False))
        if args.status:
            return 0
        print({"content": "no ad - left alone",
               "skipped-button": "ad skipped (button)",
               "seeked-end": "ad seeked to its end",
               "wait": "ad playing, nothing to click yet"}.get(res.get("state"), res.get("state")))
        return 0

    print(f"polling {tab['url']} every {args.loop}s - Ctrl-C to stop")
    try:
        while True:
            res = evaluate(tab, AD_JS)
            if res.get("ad"):
                print(f"{time.strftime('%H:%M:%S')}  ad -> {res.get('state')}"
                      f" (dur={res.get('dur')})")
            time.sleep(args.loop)
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
