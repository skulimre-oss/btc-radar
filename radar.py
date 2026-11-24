import csv
import os
from datetime import datetime, timezone
import requests

HISTORY_FILE = "history.csv"
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

BTC_MOVE_THRESHOLD_PCT = 3.0
CB_PREMIUM_THRESHOLD_PCT = 0.15
STABLECOIN_DELTA_M = 500.0


def fetch_coinbase_btc():
    r = requests.get("https://api.exchange.coinbase.com/products/BTC-USD/ticker", timeout=15)
    r.raise_for_status()
    data = r.json()
    return float(data["price"]), float(data["volume"])


def fetch_gate_btc():
    r = requests.get("https://api.gateio.ws/api/v4/spot/tickers?currency_pair=BTC_USDT", timeout=15)
    r.raise_for_status()
    data = r.json()[0]
    return float(data["last"]), float(data["quote_volume"]), float(data["change_percentage"])


def fetch_stablecoin_cap_m():
    r = requests.get("https://stablecoins.llama.fi/stablecoins?includePrices=false", timeout=20)
    r.raise_for_status()
    assets = r.json().get("peggedAssets", [])
    total_usd = 0.0
    for asset in assets:
        circ = asset.get("circulating", {}).get("peggedUSD", 0.0)
        if isinstance(circ, (int, float)):
            total_usd += circ
    return round(total_usd / 1_000_000, 2)


def read_last_row():
    if not os.path.exists(HISTORY_FILE):
        return None
    with open(HISTORY_FILE, mode="r", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        return rows[-1] if rows else None


def append_row(row):
    file_exists = os.path.exists(HISTORY_FILE)
    fieldnames = [
        "timestamp_utc",
        "gate_btc_usdt",
        "coinbase_btc_usd",
        "cb_premium_pct",
        "gate_chg_24h_pct",
        "gate_vol_24h_usdt_m",
        "stablecoins_total_m",
        "regime",
    ]
    with open(HISTORY_FILE, mode="a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram non configuré :", message)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=15)


def main():
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cb_price, _ = fetch_coinbase_btc()
    gate_price, gate_vol_usdt, gate_chg_24h = fetch_gate_btc()
    stable_m = fetch_stablecoin_cap_m()

    cb_premium_pct = round(((cb_price - gate_price) / gate_price) * 100, 4)
    prev = read_last_row()

    alerts = []
    regime = "NORMAL"

    if prev:
        prev_btc = float(prev["gate_btc_usdt"])
        prev_stable = float(prev["stablecoins_total_m"])
        btc_step_pct = ((gate_price - prev_btc) / prev_btc) * 100
        stable_delta_m = stable_m - prev_stable

        if abs(btc_step_pct) >= BTC_MOVE_THRESHOLD_PCT:
            regime = "ALERT_TRIGGERED"
            alerts.append(f"Mouvement BTC rapide : {btc_step_pct:+.2f}% (vs {prev_btc:,.1f} $)")

        if abs(stable_delta_m) >= STABLECOIN_DELTA_M:
            regime = "ALERT_TRIGGERED"
            alerts.append(f"Flux Stablecoins global : {stable_delta_m:+.1f} M$")

    if abs(cb_premium_pct) >= CB_PREMIUM_THRESHOLD_PCT:
        if regime == "NORMAL":
            regime = "ACTIVE_MOVE"
        alerts.append(f"Coinbase Premium marqué : {cb_premium_pct:+.3f}%")

    row = {
        "timestamp_utc": now_utc,
        "gate_btc_usdt": round(gate_price, 2),
        "coinbase_btc_usd": round(cb_price, 2),
        "cb_premium_pct": cb_premium_pct,
        "gate_chg_24h_pct": round(gate_chg_24h, 2),
        "gate_vol_24h_usdt_m": round(gate_vol_usdt / 1_000_000, 2),
        "stablecoins_total_m": stable_m,
        "regime": regime,
    }
    append_row(row)
    print("Relevé enregistré :", row)

    if alerts or prev is None:
        header = "🚀 BTC RADAR — Initialisation" if prev is None else f"🚨 BTC RADAR [{regime}]"
        details = "\n• ".join(alerts) if alerts else "Premier relevé enregistré avec succès."
        msg = (
            f"{header}\n"
            f"🕒 {now_utc}\n"
            f"₿ Gate BTC : {gate_price:,.2f} $ ({gate_chg_24h:+.2f}% / 24h)\n"
            f"🇺🇸 Coinbase : {cb_price:,.2f} $ (Premium : {cb_premium_pct:+.3f}%)\n"
            f"💵 Stablecoins : {stable_m:,.2f} M$\n\n"
            f"• {details}"
        )
        send_telegram(msg)


if __name__ == "__main__":
    main()
