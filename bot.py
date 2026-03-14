#!/usr/bin/env python3
"""
╔═══════════════════════════════════════════════╗
║        🚀 CRYPTOSIGNAL BOT v1.0               ║
║   Telegram Bot — Live Signals & Crypto Intel  ║
╚═══════════════════════════════════════════════╝
"""

import asyncio
import logging
import os
from datetime import datetime
from typing import Optional

import aiohttp
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes
)

# ──────────────────────────────────────────────
# ⚙️  CONFIG — Edit before running!
# ──────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "8741112903:AAF4EiT2gAc5bOkHBDuH64YW9PtLmD2WfYc")
ALERT_CHANNEL_ID = os.getenv("ALERT_CHANNEL_ID", "YOUR_CHANNEL_ID_HERE")

TRACKED_COINS = [
    "bitcoin", "ethereum", "solana", "binancecoin",
    "ripple", "cardano", "dogecoin", "avalanche-2",
    "chainlink", "polkadot"
]

COIN_SYMBOLS = {
    "bitcoin": "BTC", "ethereum": "ETH", "solana": "SOL",
    "binancecoin": "BNB", "ripple": "XRP", "cardano": "ADA",
    "dogecoin": "DOGE", "avalanche-2": "AVAX",
    "chainlink": "LINK", "polkadot": "DOT"
}

PRICE_ALERT_THRESHOLD = 5.0   # % move triggers alert
RSI_OVERSOLD        = 30
RSI_OVERBOUGHT      = 70
CHECK_INTERVAL      = 900     # seconds (15 min)

COINGECKO = "https://api.coingecko.com/api/v3"

# ──────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s │ %(levelname)s │ %(message)s",
    level=logging.INFO
)
log = logging.getLogger(__name__)

subscribers: set = set()
price_history: dict = {}


# ════════════════════════════════════════════════
# 📡  DATA LAYER
# ════════════════════════════════════════════════

async def get_market_data(coins: list) -> Optional[list]:
    ids = ",".join(coins)
    url = (
        f"{COINGECKO}/coins/markets?vs_currency=usd&ids={ids}"
        f"&order=market_cap_desc&per_page=50&page=1"
        f"&sparkline=true&price_change_percentage=1h,24h,7d"
    )
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status == 200:
                    return await r.json()
                log.warning(f"CoinGecko returned {r.status}")
    except Exception as e:
        log.error(f"Market data error: {e}")
    return None


async def get_global_stats() -> Optional[dict]:
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{COINGECKO}/global", timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status == 200:
                    return (await r.json()).get("data", {})
    except Exception as e:
        log.error(f"Global stats error: {e}")
    return None


async def get_trending() -> Optional[list]:
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{COINGECKO}/search/trending", timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status == 200:
                    data = await r.json()
                    return data.get("coins", [])[:7]
    except Exception as e:
        log.error(f"Trending error: {e}")
    return None


async def get_fear_greed() -> Optional[dict]:
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://api.alternative.me/fng/", timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status == 200:
                    data = await r.json()
                    return data["data"][0]
    except Exception as e:
        log.error(f"Fear & Greed error: {e}")
    return None


# ════════════════════════════════════════════════
# 🧠  SIGNAL ENGINE
# ════════════════════════════════════════════════

def compute_rsi(prices: list, period: int = 14) -> Optional[float]:
    if len(prices) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(prices)):
        delta = prices[i] - prices[i - 1]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


def compute_sma(prices: list, period: int) -> Optional[float]:
    if len(prices) < period:
        return None
    return round(sum(prices[-period:]) / period, 6)


def generate_signal(coin: dict) -> dict:
    """Full signal analysis for a single coin"""
    spark = coin.get("sparkline_in_7d", {}).get("price", [])
    price = coin.get("current_price", 0)
    change_1h  = coin.get("price_change_percentage_1h_in_currency", 0) or 0
    change_24h = coin.get("price_change_percentage_24h_in_currency", 0) or 0
    change_7d  = coin.get("price_change_percentage_7d_in_currency", 0) or 0
    volume     = coin.get("total_volume", 0)
    mcap       = coin.get("market_cap", 0)

    rsi    = compute_rsi(spark) if spark else None
    sma7   = compute_sma(spark, 49)   # ~7d hourly
    sma25  = compute_sma(spark, 168)  # full 7d

    score = 0
    reasons = []

    # RSI scoring
    if rsi:
        if rsi < RSI_OVERSOLD:
            score += 3
            reasons.append(f"RSI oversold ({rsi})")
        elif rsi > RSI_OVERBOUGHT:
            score -= 3
            reasons.append(f"RSI overbought ({rsi})")
        elif rsi < 45:
            score += 1
            reasons.append(f"RSI neutral-low ({rsi})")
        else:
            reasons.append(f"RSI neutral ({rsi})")

    # Moving average crossover
    if sma7 and sma25:
        if sma7 > sma25:
            score += 2
            reasons.append("SMA bullish crossover ↑")
        else:
            score -= 2
            reasons.append("SMA bearish crossover ↓")

    # Momentum (24h change)
    if change_24h > 5:
        score += 1
        reasons.append(f"Strong 24h momentum +{change_24h:.1f}%")
    elif change_24h < -5:
        score -= 1
        reasons.append(f"Weak 24h momentum {change_24h:.1f}%")

    # Volume signal (crude)
    if volume and mcap:
        vol_ratio = volume / mcap
        if vol_ratio > 0.15:
            score += 1
            reasons.append(f"High volume ratio ({vol_ratio:.2f})")

    # Determine signal
    if score >= 4:
        signal, emoji = "STRONG BUY", "🟢🟢"
    elif score >= 2:
        signal, emoji = "BUY", "🟢"
    elif score <= -4:
        signal, emoji = "STRONG SELL", "🔴🔴"
    elif score <= -2:
        signal, emoji = "SELL", "🔴"
    else:
        signal, emoji = "HOLD", "🟡"

    return {
        "signal": signal,
        "emoji": emoji,
        "score": score,
        "rsi": rsi,
        "sma7": sma7,
        "sma25": sma25,
        "change_1h": change_1h,
        "change_24h": change_24h,
        "change_7d": change_7d,
        "reasons": reasons,
        "price": price,
    }


# ════════════════════════════════════════════════
# 💬  MESSAGE FORMATTERS
# ════════════════════════════════════════════════

def fmt_price(price: float) -> str:
    if price >= 1000:
        return f"${price:,.2f}"
    elif price >= 1:
        return f"${price:.4f}"
    else:
        return f"${price:.6f}"


def fmt_change(pct: float) -> str:
    arrow = "▲" if pct >= 0 else "▼"
    sign  = "+" if pct >= 0 else ""
    return f"{arrow} {sign}{pct:.2f}%"


def fmt_large(n: float) -> str:
    if n >= 1e12: return f"${n/1e12:.2f}T"
    if n >= 1e9:  return f"${n/1e9:.2f}B"
    if n >= 1e6:  return f"${n/1e6:.2f}M"
    return f"${n:,.0f}"


def build_signal_message(coin: dict, sig: dict) -> str:
    name   = coin.get("name", "?")
    sym    = coin.get("symbol", "?").upper()
    price  = fmt_price(sig["price"])
    mcap   = fmt_large(coin.get("market_cap", 0))
    vol    = fmt_large(coin.get("total_volume", 0))
    rank   = coin.get("market_cap_rank", "?")
    high   = fmt_price(coin.get("high_24h", 0))
    low    = fmt_price(coin.get("low_24h", 0))

    rsi_bar = ""
    if sig["rsi"]:
        filled = int(sig["rsi"] / 10)
        rsi_bar = "█" * filled + "░" * (10 - filled)

    reasons_text = "\n".join(f"  › {r}" for r in sig["reasons"]) or "  › No clear signal"

    msg = f"""
╔══════════════════════════════╗
║  {sig['emoji']}  {name} ({sym})  #{rank}
╚══════════════════════════════╝

💰 *Price:* {price}
📊 *Signal:* *{sig['signal']}*  (score: {sig['score']:+d})

📈 *Performance*
  1h:  {fmt_change(sig['change_1h'])}
  24h: {fmt_change(sig['change_24h'])}
  7d:  {fmt_change(sig['change_7d'])}

📉 *24h Range*
  Low: {low}  ·  High: {high}

🔬 *Indicators*
  RSI: {sig['rsi'] if sig['rsi'] else 'N/A'} [{rsi_bar}]
  SMA7:  {fmt_price(sig['sma7']) if sig['sma7'] else 'N/A'}
  SMA25: {fmt_price(sig['sma25']) if sig['sma25'] else 'N/A'}

🏦 *Market*
  Cap: {mcap}  ·  Vol: {vol}

🧠 *Analysis*
{reasons_text}

⏱ {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}
""".strip()
    return msg


def build_market_overview(coins: list, global_data: dict, fg: dict) -> str:
    header = "╔══════════════════════════════╗\n║  📡  MARKET OVERVIEW          ║\n╚══════════════════════════════╝\n"

    # Global stats
    btc_dom = global_data.get("market_cap_percentage", {}).get("btc", 0)
    eth_dom = global_data.get("market_cap_percentage", {}).get("eth", 0)
    total_mc = global_data.get("total_market_cap", {}).get("usd", 0)
    total_vol = global_data.get("total_volume", {}).get("usd", 0)
    mc_change = global_data.get("market_cap_change_percentage_24h_usd", 0)

    fg_value = fg.get("value", "?") if fg else "?"
    fg_class  = fg.get("value_classification", "Unknown") if fg else "Unknown"
    fg_emoji  = "😱" if int(fg_value) < 25 else "😨" if int(fg_value) < 45 else "😐" if int(fg_value) < 55 else "😊" if int(fg_value) < 75 else "🤑"

    stats = f"""
🌍 *Global Stats*
  Total Market Cap: {fmt_large(total_mc)}  ({fmt_change(mc_change)})
  24h Volume: {fmt_large(total_vol)}
  BTC Dominance: {btc_dom:.1f}%  ·  ETH: {eth_dom:.1f}%

{fg_emoji} *Fear & Greed Index:* {fg_value}/100 — _{fg_class}_

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

    rows = []
    for c in coins[:8]:
        sig = generate_signal(c)
        sym = c.get("symbol", "").upper().ljust(5)
        pr  = fmt_price(c.get("current_price", 0)).rjust(14)
        ch  = fmt_change(sig["change_24h"]).rjust(12)
        rows.append(f"  {sig['emoji']} `{sym}` {pr}  {ch}")

    coin_table = "\n".join(rows)

    footer = f"\n\n⏱ {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
    return header + stats + coin_table + footer


def build_trending_message(trending: list) -> str:
    msg = "╔══════════════════════════════╗\n║  🔥  TRENDING COINS           ║\n╚══════════════════════════════╝\n\n"
    for i, item in enumerate(trending, 1):
        c = item.get("item", {})
        name = c.get("name", "?")
        sym  = c.get("symbol", "?").upper()
        rank = c.get("market_cap_rank", "?")
        score = c.get("score", 0)
        msg += f"  {i}. *{name}* ({sym})  |  Rank #{rank}  |  Score: {score}\n"
    msg += f"\n⏱ {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
    return msg


# ════════════════════════════════════════════════
# 🤖  BOT COMMANDS
# ════════════════════════════════════════════════

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_chat.id
    subscribers.add(uid)
    kb = [
        [InlineKeyboardButton("📡 Market Overview", callback_data="market"),
         InlineKeyboardButton("🔥 Trending", callback_data="trending")],
        [InlineKeyboardButton("📊 BTC Signal", callback_data="sig_bitcoin"),
         InlineKeyboardButton("📊 ETH Signal", callback_data="sig_ethereum")],
        [InlineKeyboardButton("📊 SOL Signal", callback_data="sig_solana"),
         InlineKeyboardButton("📊 BNB Signal", callback_data="sig_binancecoin")],
        [InlineKeyboardButton("🔔 Subscribe Alerts", callback_data="subscribe"),
         InlineKeyboardButton("🔕 Unsubscribe", callback_data="unsubscribe")],
        [InlineKeyboardButton("💡 All Signals", callback_data="all_signals"),
         InlineKeyboardButton("ℹ️ Help", callback_data="help")],
    ]
    markup = InlineKeyboardMarkup(kb)
    welcome = """
╔══════════════════════════════╗
║  🚀  CRYPTOSIGNAL BOT        ║
╚══════════════════════════════╝

Welcome to *CryptoSignal Bot* — your real-time crypto intelligence hub.

*What I can do:*
› Live prices & market overview
› Buy/Sell/Hold signals (RSI + SMA)
› Fear & Greed index
› Trending coins
› Automatic price alerts (±5%)
› Technical analysis per coin

_Data powered by CoinGecko API_

Use the buttons below or type /help
""".strip()
    await update.message.reply_text(welcome, parse_mode="Markdown", reply_markup=markup)


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = """
╔══════════════════════════════╗
║  ℹ️  COMMANDS                ║
╚══════════════════════════════╝

/start       — Main menu
/market      — Full market overview
/signal BTC  — Signal for any coin
/trending    — Trending coins
/top         — Top 10 by market cap
/alerts      — Subscribe to auto-alerts
/fear        — Fear & Greed Index
/help        — This message

*Examples:*
  /signal ETH
  /signal SOL
  /signal DOGE
""".strip()
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_market(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("⏳ Fetching live market data...")
    coins = await get_market_data(TRACKED_COINS)
    gdata = await get_global_stats()
    fg    = await get_fear_greed()
    if not coins or not gdata:
        await msg.edit_text("⚠️ Could not fetch data. Try again shortly.")
        return
    text = build_market_overview(coins, gdata, fg)
    kb   = [[InlineKeyboardButton("🔄 Refresh", callback_data="market")]]
    await msg.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))


async def cmd_signal(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args
    if not args:
        await update.message.reply_text("Usage: /signal BTC  or  /signal ETH")
        return
    sym_input = args[0].upper()
    coin_id = next((k for k, v in COIN_SYMBOLS.items() if v == sym_input), None)
    if not coin_id:
        coin_id = sym_input.lower()

    msg = await update.message.reply_text(f"⏳ Analysing {sym_input}...")
    coins = await get_market_data([coin_id])
    if not coins:
        await msg.edit_text("⚠️ Coin not found or API error. Check the symbol.")
        return
    coin = coins[0]
    sig  = generate_signal(coin)
    text = build_signal_message(coin, sig)
    kb   = [[InlineKeyboardButton("🔄 Refresh", callback_data=f"sig_{coin_id}")]]
    await msg.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))


async def cmd_trending(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("⏳ Fetching trending coins...")
    trending = await get_trending()
    if not trending:
        await msg.edit_text("⚠️ Could not fetch trending data.")
        return
    await msg.edit_text(build_trending_message(trending), parse_mode="Markdown")


async def cmd_fear(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    fg = await get_fear_greed()
    if not fg:
        await update.message.reply_text("⚠️ Could not fetch Fear & Greed data.")
        return
    val = int(fg.get("value", 0))
    cls = fg.get("value_classification", "Unknown")
    updated = fg.get("timestamp", "")

    bar_filled = int(val / 10)
    bar = "█" * bar_filled + "░" * (10 - bar_filled)

    if val < 25:   emoji, advice = "😱", "Extreme fear — historically a BUY opportunity"
    elif val < 45: emoji, advice = "😨", "Fear in the market — consider accumulating"
    elif val < 55: emoji, advice = "😐", "Neutral — wait for clearer signals"
    elif val < 75: emoji, advice = "😊", "Greed present — manage your risk"
    else:          emoji, advice = "🤑", "Extreme greed — consider taking profits"

    text = f"""
╔══════════════════════════════╗
║  {emoji}  FEAR & GREED INDEX      ║
╚══════════════════════════════╝

*Score:* {val}/100 — _{cls}_
*Meter:* [{bar}]

💡 *Advice:* {advice}

_When others are fearful, be greedy._
_When others are greedy, be fearful._
— Warren Buffett
""".strip()
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_top(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("⏳ Loading top coins...")
    coins = await get_market_data(TRACKED_COINS)
    if not coins:
        await msg.edit_text("⚠️ Could not fetch data.")
        return
    text = "╔══════════════════════════════╗\n║  🏆  TOP COINS BY MARKET CAP  ║\n╚══════════════════════════════╝\n\n"
    for i, c in enumerate(coins[:10], 1):
        sym = c.get("symbol", "").upper()
        price = fmt_price(c.get("current_price", 0))
        ch24  = c.get("price_change_percentage_24h_in_currency", 0) or 0
        mcap  = fmt_large(c.get("market_cap", 0))
        arrow = "▲" if ch24 >= 0 else "▼"
        text += f"  {i:>2}. *{sym}*  {price}  {arrow}{abs(ch24):.2f}%  ·  {mcap}\n"
    text += f"\n⏱ {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
    await msg.edit_text(text, parse_mode="Markdown")


async def cmd_alerts(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_chat.id
    subscribers.add(uid)
    await update.message.reply_text(
        "✅ *Subscribed to auto-alerts!*\n\nYou'll receive:\n› Signals every 15 minutes\n› Price spike/crash alerts (±5%)\n› Market mood updates\n\nType /start to return to menu.",
        parse_mode="Markdown"
    )


# ════════════════════════════════════════════════
# 🖱  BUTTON CALLBACKS
# ════════════════════════════════════════════════

async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "market":
        coins = await get_market_data(TRACKED_COINS)
        gdata = await get_global_stats()
        fg    = await get_fear_greed()
        if coins and gdata:
            text = build_market_overview(coins, gdata, fg)
            kb   = [[InlineKeyboardButton("🔄 Refresh", callback_data="market")]]
            await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

    elif data == "trending":
        trending = await get_trending()
        if trending:
            await query.edit_message_text(build_trending_message(trending), parse_mode="Markdown")

    elif data == "all_signals":
        await query.edit_message_text("⏳ Generating signals for all tracked coins...")
        coins = await get_market_data(TRACKED_COINS)
        if not coins:
            await query.edit_message_text("⚠️ API error. Try again.")
            return
        summary = "╔══════════════════════════════╗\n║  📊  ALL SIGNALS              ║\n╚══════════════════════════════╝\n\n"
        for c in coins:
            sig = generate_signal(c)
            sym = c.get("symbol", "").upper().ljust(5)
            pr  = fmt_price(sig["price"]).rjust(14)
            rsi_str = f"RSI:{sig['rsi']}" if sig["rsi"] else "RSI:N/A"
            summary += f"  {sig['emoji']} `{sym}` {pr}  *{sig['signal']}*  ({rsi_str})\n"
        summary += f"\n⏱ {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
        kb = [[InlineKeyboardButton("🔄 Refresh", callback_data="all_signals")]]
        await query.edit_message_text(summary, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("sig_"):
        coin_id = data[4:]
        await query.edit_message_text(f"⏳ Analysing {coin_id.upper()}...")
        coins = await get_market_data([coin_id])
        if not coins:
            await query.edit_message_text("⚠️ API error. Try again.")
            return
        coin = coins[0]
        sig  = generate_signal(coin)
        text = build_signal_message(coin, sig)
        kb   = [[InlineKeyboardButton("🔄 Refresh", callback_data=f"sig_{coin_id}")]]
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

    elif data == "subscribe":
        subscribers.add(query.from_user.id)
        await query.answer("✅ Subscribed to auto-alerts!", show_alert=True)

    elif data == "unsubscribe":
        subscribers.discard(query.from_user.id)
        await query.answer("🔕 Unsubscribed from alerts.", show_alert=True)

    elif data == "help":
        text = "Commands: /market /signal BTC /trending /top /fear /alerts\n\nUse buttons or type any command with a coin symbol."
        await query.edit_message_text(text)


# ════════════════════════════════════════════════
# ⏰  SCHEDULED JOBS
# ════════════════════════════════════════════════

async def job_check_alerts(ctx: ContextTypes.DEFAULT_TYPE):
    """Runs every 15 min — checks for big moves and sends signals"""
    if not subscribers:
        return

    coins = await get_market_data(TRACKED_COINS)
    if not coins:
        return

    alerts_sent = []
    for coin in coins:
        cid   = coin.get("id")
        price = coin.get("current_price", 0)
        ch1h  = coin.get("price_change_percentage_1h_in_currency", 0) or 0
        ch24h = coin.get("price_change_percentage_24h_in_currency", 0) or 0
        sym   = coin.get("symbol", "").upper()
        sig   = generate_signal(coin)

        # Check for strong RSI signals
        if sig["rsi"] and (sig["rsi"] < RSI_OVERSOLD or sig["rsi"] > RSI_OVERBOUGHT):
            alerts_sent.append(coin)

        # Check for price spikes
        if abs(ch1h) >= PRICE_ALERT_THRESHOLD:
            direction = "🚀 PUMP" if ch1h > 0 else "💥 DUMP"
            alert = f"""
⚡ *PRICE ALERT — {direction}*

*{sym}* moved {fmt_change(ch1h)} in 1 hour!
Price: {fmt_price(price)}
24h: {fmt_change(ch24h)}
Signal: {sig['emoji']} *{sig['signal']}*

⏱ {datetime.utcnow().strftime('%H:%M UTC')}
""".strip()
            for uid in subscribers:
                try:
                    await ctx.bot.send_message(uid, alert, parse_mode="Markdown")
                except Exception:
                    pass

    # Send periodic signal digest
    if alerts_sent:
        digest = "📡 *SIGNAL DIGEST*\n\n"
        for coin in alerts_sent[:5]:
            sig = generate_signal(coin)
            sym = coin.get("symbol", "").upper()
            digest += f"  {sig['emoji']} *{sym}* — {sig['signal']}  (RSI: {sig['rsi']})\n"
        digest += f"\n⏱ {datetime.utcnow().strftime('%H:%M UTC')}"
        for uid in subscribers:
            try:
                await ctx.bot.send_message(uid, digest, parse_mode="Markdown")
            except Exception:
                pass


async def job_daily_report(ctx: ContextTypes.DEFAULT_TYPE):
    """Daily market summary at 9:00 UTC"""
    if not subscribers:
        return

    coins = await get_market_data(TRACKED_COINS)
    gdata = await get_global_stats()
    fg    = await get_fear_greed()
    if not coins or not gdata:
        return

    text = build_market_overview(coins, gdata, fg)
    header = "🌅 *DAILY MARKET REPORT*\n\n"
    for uid in subscribers:
        try:
            await ctx.bot.send_message(uid, header + text, parse_mode="Markdown")
        except Exception:
            pass


# ════════════════════════════════════════════════
# 🚀  MAIN
# ════════════════════════════════════════════════

async def post_init(app: Application):
    await app.bot.set_my_commands([
        BotCommand("start",    "Main menu"),
        BotCommand("market",   "Live market overview"),
        BotCommand("signal",   "Signal for a coin (e.g. /signal BTC)"),
        BotCommand("trending", "Trending coins"),
        BotCommand("top",      "Top 10 by market cap"),
        BotCommand("fear",     "Fear & Greed index"),
        BotCommand("alerts",   "Subscribe to auto-alerts"),
        BotCommand("help",     "Help & commands"),
    ])


def main():
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌  Set your BOT_TOKEN in bot.py or as environment variable BOT_TOKEN=...")
        return

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # Register handlers
    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("help",     cmd_help))
    app.add_handler(CommandHandler("market",   cmd_market))
    app.add_handler(CommandHandler("signal",   cmd_signal))
    app.add_handler(CommandHandler("trending", cmd_trending))
    app.add_handler(CommandHandler("fear",     cmd_fear))
    app.add_handler(CommandHandler("top",      cmd_top))
    app.add_handler(CommandHandler("alerts",   cmd_alerts))
    app.add_handler(CallbackQueryHandler(on_button))

    # Schedule jobs
    jq = app.job_queue
    jq.run_repeating(job_check_alerts, interval=CHECK_INTERVAL, first=60)
    jq.run_daily(job_daily_report, time=datetime.strptime("09:00", "%H:%M").time())

    print("🚀 CryptoSignal Bot is running...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
