#!/usr/bin/env python3
"""
Trending di Indonesia
=====================
Mengambil 25 tren penelusuran Google Trends Indonesia (24 jam terakhir) langsung
dari https://trends.google.com/trending?geo=ID — lengkap dengan volume penelusuran,
persentase kenaikan, sejak kapan aktif, dan kueri terkait — lalu memperbarui
tabel di README.md.

Cara pakai:
    python3 scrape_trending.py            # update README.md
    python3 scrape_trending.py --print    # hanya tampilkan hasil di terminal

Tidak butuh API key / dependensi eksternal (stdlib murni, Python 3.8+).
"""
import html
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone, timedelta

URL = "https://trends.google.com/trending?geo=ID&hl=id"
README = "README.md"

WIB = timezone(timedelta(hours=7))
BULAN_ID = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli",
            "Agustus", "September", "Oktober", "November", "Desember"]


def fetch_page():
    req = urllib.request.Request(URL, headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
        "Accept-Language": "id-ID,id;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", errors="replace")


def parse(htmlsrc):
    """Ekstrak baris tren dari HTML SSR halaman trending."""
    rows = []
    for t in re.split(r"<tr[ >]", htmlsrc):
        if 'class="mZ3RIc"' not in t:
            continue
        mq = re.search(r'class="mZ3RIc">([^<]+)<', t)
        if not mq:
            continue
        vol = re.search(r'<div class="lqv0Cb">([^<]+)</div>', t)
        pct = re.search(r'<div class="TXt85b">([^<]+)</div>', t)
        since = re.search(r'<div class="vdw3Ld"[^>]*>([^<]+)</div>', t)
        seen, rel = set(), []
        for term in re.findall(r'data-term="([^"]+)"', t):
            if term not in seen:
                seen.add(term)
                rel.append(term)
        rows.append({
            "query": html.unescape(mq.group(1)).strip(),
            "volume": vol.group(1).replace("\xa0", " ") if vol else "",
            "change": pct.group(1) if pct else "",
            "active_since": html.unescape(since.group(1)) if since else "",
            "related": rel,
        })
    return rows


def build_table(rows):
    lines = []
    lines.append("| # | Tren | Volume Penelusuran | Kenaikan | Aktif Sejak | Kueri Terkait |")
    lines.append("|---|---|---|---|---|---|")
    for i, r in enumerate(rows, 1):
        q = r["query"].replace("|", "\\|")
        rel = ", ".join(x.replace("|", "\\|") for x in r["related"][:3]) or "–"
        lines.append(
            f"| {i} | **{q}** | {r['volume'] or '–'} | {r['change'] or '–'} "
            f"| {r['active_since'] or '–'} | {rel} |"
        )
    return "\n".join(lines)


def main():
    show_only = "--print" in sys.argv
    print("Mengambil halaman Google Trends ID...")
    rows = parse(fetch_page())
    print(f"Dapat {len(rows)} tren")
    if not rows:
        print("Tidak ada data, batal.")
        return 1

    table = build_table(rows)
    if show_only:
        print(table)
        return 0

    now = datetime.now(WIB)
    updated = now.strftime(f"%d {BULAN_ID[now.month - 1]} %Y, %H:%M WIB")
    top = rows[0]
    total_vol = sum(int(re.sub(r"[^\d]", "", r["volume"]) or 0) for r in rows)

    header = f"""# 🔥 Trending di Indonesia

**25 tren penelusuran teratas** di Google Trends Indonesia (24 jam terakhir) — diperbarui otomatis **setiap 2 jam** langsung dari [Google Trends](https://trends.google.com/trending?geo=ID).

> 🕒 **Terakhir diperbarui: {updated}**

## 🏆 Tren Paling Panas

| | Tren | Volume | Kenaikan |
|---|---|---|---|
| 🥇 | **{rows[0]['query']}** | {rows[0]['volume']} | ▲ {rows[0]['change']} |
| 🥈 | **{rows[1]['query']}** | {rows[1]['volume']} | ▲ {rows[1]['change']} |
| 🥉 | **{rows[2]['query']}** | {rows[2]['volume']} | ▲ {rows[2]['change']} |

*Total volume penelusuran gabungan: ±{total_vol:,}+ penelusuran*

## 📋 Daftar Lengkap 25 Tren

{table}
"""
    footer = """
## 📖 Keterangan Kolom

- **Tren** — kata kunci yang sedang banyak dicari di Google Indonesia
- **Volume Penelusuran** — estimasi jumlah penelusuran (rb+ = ribuan, jt+ = jutaan)
- **Kenaikan** — persentase lonjakan volume dibanding periode sebelumnya
- **Aktif Sejak** — berapa lama tren ini mulai naik daun
- **Kueri Terkait** — pencarian lain yang muncul bersama tren tersebut

## ⚙️ Cara Kerja

Script `scrape_trending.py` mengambil data langsung dari halaman trending Google Trends Indonesia dan memperbarui tabel di halaman ini otomatis setiap 2 jam.

Jalankan sendiri:

```bash
python3 scrape_trending.py          # update README.md
python3 scrape_trending.py --print  # lihat hasil di terminal
```

Tanpa dependensi eksternal — cukup Python 3.8+.

## 👥 Kunjungan

<img src="https://s01.flagcounter.com/countxl/qaoY/bg_FFFFFF/txt_000000/border_CCCCCC/columns_2/maxflags_10/viewers_0/labels_0/pageviews_1/flags_0/percent_0/" alt="Visitor Counter">

---

*by PT. Pastiin Siber Indonesia*
"""
    # rapikan angka total volume (ganti koma ribuan jadi titik)
    header = header.replace(f"{total_vol:,}", f"{total_vol:,}".replace(",", "."))
    content = header + "\n" + table + "\n" + footer
    with open(README, "w") as f:
        f.write(content)
    print(f"README.md diperbarui ({len(rows)} tren)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
