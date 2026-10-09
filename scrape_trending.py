#!/usr/bin/env python3
"""
Trending di Indonesia
=====================
Mengambil SEMUA tren penelusuran Google Trends Indonesia (24 jam terakhir) —
bukan hanya 25 — dengan menelusuri seluruh halaman paging lewat Google Chrome/
Chromium yang berjalan dengan remote debugging (CDP).

Cara pakai:
    python3 scrape_trending.py            # update README.md
    python3 scrape_trending.py --print    # hanya tampilkan hasil di terminal

Prasyarat:
    Google Chrome/Chromium berjalan dengan --remote-debugging-port (default 9222,
    bisa di-override lewat env CDP_URL, mis. http://127.0.0.1:39221).

Tanpa API key & tanpa dependensi eksternal (stdlib murni, Python 3.8+).
"""
import base64
import json
import os
import re
import socket
import struct
import sys
import urllib.request
from datetime import datetime, timezone, timedelta

TRENDS_URL = "https://trends.google.com/trending?geo=ID&hl=id"
CDP_URL = os.environ.get("CDP_URL", "")  # override manual bila perlu


def find_cdp():
    """Cari port CDP Chrome; kalau tidak ada, luncurkan Chrome headless sendiri."""
    if CDP_URL:
        return CDP_URL
    for port in (9222, 39221):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=3):
                return f"http://127.0.0.1:{port}"
        except Exception:
            continue
    import glob
    for p in glob.glob(os.path.expanduser("~/.hermes/cache/scratch/agent-browser-chrome-*/DevToolsActivePort")) \
            + glob.glob("/tmp/.org.chromium.Chromium.*/DevToolsActivePort"):
        try:
            port = open(p).read().split()[0]
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=3):
                return f"http://127.0.0.1:{port}"
        except Exception:
            continue
    return launch_chrome()


def launch_chrome():
    """Luncurkan Chrome/Chromium headless dengan remote debugging, kembalikan base URL."""
    import glob
    import subprocess
    import time

    candidates = (glob.glob(os.path.expanduser(
        "~/.cache/ms-playwright/chromium-*/chrome-linux64/chrome"))
        + ["/usr/bin/chromium", "/usr/bin/chromium-browser",
           "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable"])
    binary = next((c for c in candidates if os.path.exists(c)), None)
    if not binary:
        raise RuntimeError("Chrome/Chromium tidak ditemukan")

    profile = os.path.expanduser("~/.trends-chrome-profile")
    os.makedirs(profile, exist_ok=True)
    subprocess.Popen(
        [binary, "--headless=new", "--no-sandbox", "--disable-gpu",
         "--disable-dev-shm-usage", "--no-first-run",
         f"--user-data-dir={profile}",
         "--remote-debugging-port=9222", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True)
    for _ in range(20):
        time.sleep(1)
        try:
            with urllib.request.urlopen("http://127.0.0.1:9222/json/version", timeout=3):
                return "http://127.0.0.1:9222"
        except Exception:
            continue
    raise RuntimeError("Chrome diluncurkan tapi CDP tidak merespons di port 9222")
README = "README.md"
MAX_PAGES = 15  # pengaman

WIB = timezone(timedelta(hours=7))
BULAN_ID = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli",
            "Agustus", "September", "Oktober", "November", "Desember"]

JS_COLLECT = r"""
(() => {
  const out = [];
  document.querySelectorAll('tr').forEach(t => {
    const q = t.querySelector('.mZ3RIc');
    if (!q) return;
    const vol = t.querySelector('.lqv0Cb');
    const pct = t.querySelector('.TXt85b');
    const since = t.querySelector('.vdw3Ld');
    const seen = new Set();
    const rel = [];
    t.querySelectorAll('[data-term]').forEach(e => {
      const d = e.getAttribute('data-term');
      if (d && !seen.has(d)) { seen.add(d); rel.push(d); }
    });
    out.push({
      query: q.innerText.trim(),
      volume: vol ? vol.innerText.trim() : '',
      change: pct ? pct.innerText.trim() : '',
      since: since ? since.innerText.trim() : '',
      related: rel.slice(0, 4),
    });
  });
  const next = [...document.querySelectorAll('button')].find(
    b => b.getAttribute('aria-label') === 'Buka halaman berikutnya');
  const disabled = next ? (next.disabled || next.getAttribute('aria-disabled') === 'true') : true;
  return JSON.stringify({rows: out, hasNext: !disabled});
})()
"""

JS_CLICK_NEXT = r"""
(() => {
  const next = [...document.querySelectorAll('button')].find(
    b => b.getAttribute('aria-label') === 'Buka halaman berikutnya');
  if (next) { next.click(); return true; }
  return false;
})()
"""


# ---------- CDP helpers (websocket + HTTP, stdlib murni) ----------

def _http_json(path):
    base = find_cdp()
    with urllib.request.urlopen(base + path, timeout=15) as r:
        return json.load(r)


class CDP:
    """Klien CDP minimal di atas satu websocket tab."""

    def __init__(self):
        targets = _http_json("/json/list")
        page = next((t for t in targets if t["type"] == "page"), targets[0])
        self.ws_url = page["webSocketDebuggerUrl"]
        self.sock = self._ws_connect(self.ws_url)
        self._id = 0

    @staticmethod
    def _ws_connect(ws_url):
        host, port = ws_url.split("/")[2].rsplit(":", 1)
        path = "/" + ws_url.split("/", 3)[3]
        key = base64.b64encode(os.urandom(16)).decode()
        req = (f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\n"
               "Upgrade: websocket\r\nConnection: Upgrade\r\n"
               f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        sock = socket.create_connection((host, int(port)), timeout=60)
        sock.sendall(req.encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            resp += sock.recv(4096)
        if b"101" not in resp.split(b"\r\n", 1)[0]:
            raise ConnectionError("websocket handshake gagal: " + resp[:120].decode(errors="replace"))
        return sock

    @staticmethod
    def _read_exact(sock, n):
        buf = b""
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("websocket tertutup")
            buf += chunk
        return buf

    def _recv_frame(self):
        hdr = self._read_exact(self.sock, 2)
        ln = hdr[1] & 0x7F
        if ln == 126:
            ln = struct.unpack(">H", self._read_exact(self.sock, 2))[0]
        elif ln == 127:
            ln = struct.unpack(">Q", self._read_exact(self.sock, 8))[0]
        return self._read_exact(self.sock, ln).decode("utf-8", errors="replace")

    def _send_frame(self, payload: bytes):
        # client -> server harus di-mask
        mask = os.urandom(4)
        ln = len(payload)
        if ln < 126:
            hdr = struct.pack("!BB", 0x81, 0x80 | ln)
        elif ln < 65536:
            hdr = struct.pack("!BBH", 0x81, 0x80 | 126, ln)
        else:
            hdr = struct.pack("!BBQ", 0x81, 0x80 | 127, ln)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(hdr + mask + masked)

    def call(self, method, params=None):
        self._id += 1
        mid = self._id
        self._send_frame(json.dumps({"id": mid, "method": method,
                                     "params": params or {}}).encode())
        while True:
            data = json.loads(self._recv_frame())
            if data.get("id") == mid:
                if "error" in data:
                    raise RuntimeError(f"{method}: {data['error']}")
                return data.get("result", {})

    def eval_js(self, expression):
        r = self.call("Runtime.evaluate",
                      {"expression": expression, "returnByValue": True,
                       "awaitPromise": True})
        return r.get("result", {}).get("value")

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


# ---------- scraping ----------

def scrape_all():
    import time
    cdp = CDP()
    try:
        cdp.call("Page.enable")
        cdp.call("Page.navigate", {"url": TRENDS_URL})
        time.sleep(10)  # tunggu render penuh

        seen = {}
        for page in range(MAX_PAGES):
            val = cdp.eval_js(JS_COLLECT)
            if not val:
                print("  (halaman belum siap, coba lagi...)")
                time.sleep(5)
                val = cdp.eval_js(JS_COLLECT)
                if not val:
                    break
            data = json.loads(val)
            new = 0
            for row in data["rows"]:
                if row["query"] and row["query"] not in seen:
                    seen[row["query"]] = row
                    new += 1
            print(f"  halaman {page + 1}: +{new} baru (total {len(seen)})")
            if not data["hasNext"] or new == 0:
                break
            cdp.eval_js(JS_CLICK_NEXT)
            time.sleep(5)  # tunggu render halaman berikutnya
        return list(seen.values())
    finally:
        cdp.close()


# ---------- format ----------

def build_table(rows):
    lines = []
    lines.append("| # | Tren | Volume Penelusuran | Kenaikan | Aktif Sejak | Kueri Terkait |")
    lines.append("|---|---|---|---|---|---|")
    for i, r in enumerate(rows, 1):
        q = r["query"].replace("|", "\\|")
        rel = ", ".join(x.replace("|", "\\|") for x in r.get("related", [])[:3]) or "–"
        lines.append(
            f"| {i} | **{q}** | {r.get('volume') or '–'} | {r.get('change') or '–'} "
            f"| {r.get('since') or '–'} | {rel} |"
        )
    return "\n".join(lines)


def main():
    show_only = "--print" in sys.argv
    print("Mengambil SEMUA tren Google Trends ID (menelusuri semua halaman paging)...")
    rows = scrape_all()
    print(f"Dapat {len(rows)} tren")
    if not rows:
        print("Tidak ada data, batal (pastikan Chrome berjalan dengan remote debugging).")
        return 1

    table = build_table(rows)
    if show_only:
        print(table)
        return 0

    now = datetime.now(WIB)
    updated = now.strftime(f"%d {BULAN_ID[now.month - 1]} %Y, %H:%M WIB")
    total_vol = sum(int(re.sub(r"[^\d]", "", r.get("volume", "")) or 0) for r in rows)
    total_vol_fmt = f"{total_vol:,}".replace(",", ".")

    podium = "\n".join(
        f"| {medal} | **{rows[i]['query']}** | {rows[i].get('volume', '–')} | ▲ {rows[i].get('change', '–')} |"
        for i, medal in enumerate(["🥇", "🥈", "🥉"]) if i < len(rows))

    content = f"""# 🔥 Trending di Indonesia

**Semua tren penelusuran Google Trends Indonesia** (24 jam terakhir, {len(rows)} entri — seluruh halaman paging, bukan hanya 25 besar) — diperbarui otomatis **setiap 2 jam** langsung dari [Google Trends](https://trends.google.com/trending?geo=ID).

> 🕒 **Terakhir diperbarui: {updated}**

## 🏆 Tren Paling Panas

| | Tren | Volume | Kenaikan |
|---|---|---|---|
{podium}

*Total volume penelusuran gabungan: ±{total_vol_fmt}+ penelusuran*

## 📋 Daftar Lengkap {len(rows)} Tren

{table}

## 📖 Keterangan Kolom

- **Tren** — kata kunci yang sedang banyak dicari di Google Indonesia
- **Volume Penelusuran** — estimasi jumlah penelusuran (rb+ = ribuan, jt+ = jutaan)
- **Kenaikan** — persentase lonjakan volume dibanding periode sebelumnya
- **Aktif Sejak** — berapa lama tren ini mulai naik daun
- **Kueri Terkait** — pencarian lain yang muncul bersama tren tersebut

## ⚙️ Cara Kerja

Script `scrape_trending.py` menelusuri **seluruh halaman paging** halaman trending Google Trends Indonesia (bukan hanya 25 pertama) lewat Chrome/Chromium headless dengan remote debugging, lalu memperbarui tabel di halaman ini otomatis setiap 2 jam.

Jalankan sendiri:

```bash
# prasyarat: Chrome berjalan dengan remote debugging
google-chrome --headless=new --remote-debugging-port=9222 &
python3 scrape_trending.py          # update README.md
python3 scrape_trending.py --print  # lihat hasil di terminal
```

Tanpa API key & dependensi eksternal — stdlib murni (websocket CDP ditulis manual).

---

*by PT. Pastiin Siber Indonesia*
"""
    with open(README, "w") as f:
        f.write(content)
    print(f"README.md diperbarui ({len(rows)} tren)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
