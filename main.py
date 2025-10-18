import os
import time
import json
import math
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional

import aiohttp
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv(
    "OPENROUTER_MODEL", "openrouter/anthropic/claude-3.5-sonnet"
)

POLL_INTERVAL_SEC = int(os.getenv("POLL_INTERVAL_SEC", "60"))
ALERT_THRESHOLD_PCT = float(os.getenv("ALERT_THRESHOLD_PCT", "1.5"))
SEND_INTERVAL_MIN = int(os.getenv("SEND_INTERVAL_MIN", "0"))
COINS = [
    c.strip().lower()
    for c in os.getenv("COINS", "mog,pepe,ucjl,twelve").split(",")
    if c.strip()
]

# Pair Indodax untuk IDR biasanya <symbol>idr, contoh btcidr, ethidr.
# Di sini kita map otomatis: 'mog' -> 'mogidr', dst.
PAIRS = [f"{c}idr" for c in COINS]

INDODAX_SINGLE_TICKER = "https://indodax.com/api/ticker/{pair}"
INDODAX_ALL_TICKERS = "https://indodax.com/api/tickers"

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

# Simpan harga sebelumnya untuk kalkulasi change %
last_price = {}
last_summary_ts = None


async def fetch_json(session: aiohttp.ClientSession, url: str):
    try:
        async with session.get(url, timeout=15) as resp:
            resp.raise_for_status()
            return await resp.json()
    except Exception as e:
        return {"_error": str(e), "_url": url}


def parse_ticker_payload(pair: str, payload: dict):
    """
    Normalisasi respons Indodax ke dict:
    {'last': float, 'high': float, 'low': float, 'server_time': int}
    Mendukung endpoint /ticker/{pair} (prioritas) dan fallback /tickers.
    """
    # Format /api/ticker/<pair> biasanya: {"ticker":{"high":"", "low":"", "last":"", ...}, "server_time": 123}
    if "ticker" in payload and isinstance(payload["ticker"], dict):
        t = payload["ticker"]
        return {
            "last": float(t.get("last", 0.0)),
            "high": float(t.get("high", 0.0)),
            "low": float(t.get("low", 0.0)),
            "server_time": payload.get("server_time"),
        }

    # Fallback /api/tickers biasanya: {"tickers":{"btcidr":{"last":"...","high":"...","low":"..."}}, "server_time":123}
    if "tickers" in payload and isinstance(payload["tickers"], dict):
        t = payload["tickers"].get(pair, {})
        if t:
            return {
                "last": float(t.get("last", 0.0)),
                "high": float(t.get("high", 0.0)),
                "low": float(t.get("low", 0.0)),
                "server_time": payload.get("server_time"),
            }

    # Jika error
    return None


async def get_pair_price(session: aiohttp.ClientSession, pair: str):
    # Coba endpoint spesifik dulu
    data = await fetch_json(session, INDODAX_SINGLE_TICKER.format(pair=pair))
    parsed = parse_ticker_payload(pair, data or {})
    if parsed:
        return parsed

    # Fallback: ambil semua tickers dan pilih pair
    data = await fetch_json(session, INDODAX_ALL_TICKERS)
    parsed = parse_ticker_payload(pair, data or {})
    return parsed


async def send_telegram(
    session: aiohttp.ClientSession, text: str, parse_mode: str = "HTML"
):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram token/chat_id belum di-set. Lewati kirim pesan.")
        return
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    try:
        async with session.post(TELEGRAM_API, json=payload, timeout=15) as resp:
            if resp.status != 200:
                print("Gagal kirim Telegram:", await resp.text())
    except Exception as e:
        print("Error Telegram:", e)


async def openrouter_insight(session: aiohttp.ClientSession, rows: list):
    """
    rows: list of dict dengan kunci: pair, price, pct, high, low, ts
    Kembalikan string insight atau "" bila gagal atau API key kosong.
    """

    if not OPENROUTER_API_KEY or not rows:
        return ""

    # Batasi data agar prompt tetap ringkas untuk LLM
    sample_rows = rows[:5]

    prompt = (
        "Buat ringkasan singkat (maks 2 kalimat, bahasa Indonesia) soal pergerakan harga coin Indodax berikut. "
        "Sertakan insight praktis untuk trader:\n\n"
        "Sertakan interpretasi tren harga (misalnya stabil, cenderung naik, atau koreksi terbatas) berdasarkan price, high, dan low. \n\n"
        "Tambahkan estimasi area entry (buy), take profit (TP), dan cut loss (CL) dengan pendekatan\n\n"
        + json.dumps(sample_rows, ensure_ascii=False, indent=2)
    )

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    body = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {
                "role": "system",
                "content": "You are a concise market move summarizer. Respond in Indonesian.",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3
    }
    try:
        async with session.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=body,
            timeout=30,
        ) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                print(f"OpenRouter error ({resp.status}): {error_text}")
                return ""
            try:
                data = await resp.json()
                print("OpenRouter raw response:", data)
            except aiohttp.ContentTypeError:
                # Jika server tidak mengembalikan JSON valid
                raw_text = await resp.text()
                print("OpenRouter invalid JSON:", raw_text)
                return ""
            choices = data.get("choices") or []
            if not choices:
                print("OpenRouter response kosong:", data)
                return ""
            content = choices[0].get("message", {}).get("reasoning", "").strip()
            print("OpenRouter content:", content)
            return content
    except Exception as e:
        print("OpenRouter exception:", e)
        return ""


def fmt_ts(ts_int: Optional[int]):
    if not ts_int:
        return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    return (
        datetime.fromtimestamp(ts_int, tz=timezone.utc)
        .astimezone()
        .strftime("%Y-%m-%d %H:%M:%S")
    )


def fmt_money(x: float):
    # Format IDR tanpa desimal berlebihan
    if x >= 1000:
        return f"Rp{int(round(x, 0)):,}".replace(",", ".")
    return f"Rp{round(x, 2)}"


def small_change_symbol(pct: float):
    if pct > 0.0:
        return "▲"
    if pct < 0.0:
        return "▼"
    return "•"


async def loop_main():
    global last_price, last_summary_ts

    async with aiohttp.ClientSession() as session:
        while True:
            rows = []
            alerts = []

            for pair in PAIRS:
                data = await get_pair_price(session, pair)
                if not data:
                    print(f"Gagal parsing data untuk {pair}")
                    continue

                last = data["last"]
                high = data["high"]
                low = data["low"]
                ts = data["server_time"]

                prev = last_price.get(pair)
                pct = (
                    0.0
                    if prev is None
                    else ((last - prev) / prev * 100.0 if prev != 0 else 0.0)
                )
                last_price[pair] = last

                rows.append(
                    {
                        "pair": pair,
                        "price": last,
                        "pct": pct,
                        "high": high,
                        "low": low,
                        "ts": ts,
                    }
                )

                # Alert jika melewati threshold dan sudah punya prev
                if prev is not None and abs(pct) >= ALERT_THRESHOLD_PCT:
                    sign = small_change_symbol(pct)
                    alerts.append(
                        f"<b>{pair.upper()}</b> {sign} {pct:+.2f}% | Harga: <b>{fmt_money(last)}</b> "
                        f"(H:{fmt_money(high)} L:{fmt_money(low)}) • {fmt_ts(ts)}"
                    )

            # Kirim alert berbasis threshold
            if alerts:
                text = "🚨 <b>Pergerakan Harga Melewati Threshold</b>\n" + "\n".join(
                    f"• {a}" for a in alerts
                )
                # Tambahkan insight OpenRouter bila tersedia
                insight = await openrouter_insight(session, rows)
                print("OpenRouter insight:", insight)
                if insight:
                    text += f"\n\n🧠 <b>Insight</b>\n{insight}"
                await send_telegram(session, text)

            # Kirim ringkasan berkala jika diaktifkan
            if SEND_INTERVAL_MIN > 0:
                now = time.time()
                due = (last_summary_ts is None) or (
                    now - last_summary_ts >= SEND_INTERVAL_MIN * 60
                )
                if due and rows:
                    lines = []
                    for r in rows:
                        sign = small_change_symbol(r["pct"])
                        lines.append(
                            f"• <b>{r['pair'].upper()}</b> {sign} {r['pct']:+.2f}% | {fmt_money(r['price'])} "
                            f"(H:{fmt_money(r['high'])} L:{fmt_money(r['low'])})"
                        )
                    text = (
                        "🕒 <b>Ringkasan Harga</b>\n"
                        + "\n".join(lines)
                        + f"\n• {fmt_ts(rows[0]['ts'])}"
                    )
                    insight = await openrouter_insight(session, rows)
                    print("OpenRouter insight:", insight)
                    if insight:
                        text += f"\n\n🧠 <b>Insight</b>\n{insight}"
                    await send_telegram(session, text)
                    last_summary_ts = now

            await asyncio.sleep(POLL_INTERVAL_SEC)


if __name__ == "__main__":
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Harap set TELEGRAM_BOT_TOKEN dan TELEGRAM_CHAT_ID di .env")
        exit(1)
    print(
        f"Memantau: {', '.join(PAIRS)} | Interval: {POLL_INTERVAL_SEC}s | Threshold: {ALERT_THRESHOLD_PCT}%"
    )
    try:
        asyncio.run(loop_main())
    except KeyboardInterrupt:
        print("Stopped.")
