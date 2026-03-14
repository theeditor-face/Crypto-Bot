#!/usr/bin/env python3
"""
CRYPTOSIGNAL BOT v3.0 - with Telegram Mini App
"""
import logging, os
from datetime import datetime
from typing import Optional
import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, WebAppInfo
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

BOT_TOKEN      = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
WEBAPP_URL     = os.getenv("WEBAPP_URL", "YOUR_WEBAPP_URL_HERE")  # e.g. https://yourapp.netlify.app
CHECK_INTERVAL = 900
COINGECKO      = "https://api.coingecko.com/api/v3"

TRACKED_COINS = [
    "bitcoin","ethereum","solana","binancecoin","ripple",
    "cardano","dogecoin","avalanche-2","chainlink","polkadot",
    "toncoin","shiba-inu","litecoin","uniswap","pepe"
]
COIN_META = {
    "bitcoin":{"sym":"BTC"},"ethereum":{"sym":"ETH"},"solana":{"sym":"SOL"},
    "binancecoin":{"sym":"BNB"},"ripple":{"sym":"XRP"},"cardano":{"sym":"ADA"},
    "dogecoin":{"sym":"DOGE"},"avalanche-2":{"sym":"AVAX"},"chainlink":{"sym":"LINK"},
    "polkadot":{"sym":"DOT"},"toncoin":{"sym":"TON"},"shiba-inu":{"sym":"SHIB"},
    "litecoin":{"sym":"LTC"},"uniswap":{"sym":"UNI"},"pepe":{"sym":"PEPE"},
}
SYM_TO_ID = {v["sym"]:k for k,v in COIN_META.items()}

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)
subscribers: set = set()

# ── DATA ──
async def api_get(url):
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status == 200: return await r.json()
    except Exception as e: log.error(f"API: {e}")
    return None

async def get_coins(ids): return await api_get(f"{COINGECKO}/coins/markets?vs_currency=usd&ids={','.join(ids)}&order=market_cap_desc&per_page=50&page=1&sparkline=true&price_change_percentage=1h,24h,7d")
async def get_global():   return await api_get(f"{COINGECKO}/global")
async def get_trending(): return await api_get(f"{COINGECKO}/search/trending")
async def get_fg():       return await api_get("https://api.alternative.me/fng/")

# ── SIGNALS ──
def rsi(prices, p=14):
    if not prices or len(prices) < p+1: return None
    g,l = [],[]
    for i in range(1,len(prices)):
        d = prices[i]-prices[i-1]; g.append(max(d,0)); l.append(max(-d,0))
    ag = sum(g[-p:])/p; al = sum(l[-p:])/p
    return round(100-(100/(1+ag/al)),1) if al else 100.0

def sma(prices, p):
    if not prices or len(prices)<p: return None
    return sum(prices[-p:])/p

def signal(coin):
    spark = coin.get("sparkline_in_7d",{}).get("price",[])
    r = rsi(spark); s7 = sma(spark,49); s25 = sma(spark,168)
    ch = coin.get("price_change_percentage_24h_in_currency",0) or 0
    vol = coin.get("total_volume",0); mcap = coin.get("market_cap",1)
    sc = 0
    if r:
        if r<25: sc+=4
        elif r<30: sc+=3
        elif r>80: sc-=4
        elif r>70: sc-=3
        elif r<45: sc+=1
        elif r>55: sc-=1
    if s7 and s25: sc += 2 if s7>s25 else -2
    if ch>8: sc+=2
    elif ch>4: sc+=1
    elif ch<-8: sc-=2
    elif ch<-4: sc-=1
    if vol and mcap and vol/mcap>0.15: sc+=1
    if sc>=5:   return "🚀 STRONG BUY", sc, r
    elif sc>=2: return "✅ BUY", sc, r
    elif sc<=-5:return "🔻 STRONG SELL", sc, r
    elif sc<=-2:return "🔴 SELL", sc, r
    else:       return "⏸ HOLD", sc, r

# ── FORMAT ──
def fp(p):
    if not p: return "$0"
    if p>=1000: return f"${p:,.2f}"
    if p>=1:    return f"${p:.4f}"
    if p>=0.01: return f"${p:.5f}"
    return f"${p:.8f}"

def fb(n):
    if n>=1e12: return f"${n/1e12:.2f}T"
    if n>=1e9:  return f"${n/1e9:.2f}B"
    if n>=1e6:  return f"${n/1e6:.2f}M"
    return f"${n:,.0f}"

def fc(v):
    if v is None: return "─"
    return f"▲ +{v:.2f}%" if v>=0 else f"▼ {v:.2f}%"

def ts(): return datetime.utcnow().strftime("%d %b %Y · %H:%M UTC")

# ── KEYBOARDS ──
def main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Open Trading Terminal", web_app=WebAppInfo(url=WEBAPP_URL))],
        [InlineKeyboardButton("📊 Market",    callback_data="market"),
         InlineKeyboardButton("🎯 Signals",   callback_data="signals")],
        [InlineKeyboardButton("🔥 Trending",  callback_data="trending"),
         InlineKeyboardButton("😱 Fear & Greed", callback_data="fear")],
        [InlineKeyboardButton("🏆 Top 15",   callback_data="top"),
         InlineKeyboardButton("📈 Movers",   callback_data="movers")],
        [InlineKeyboardButton("🔔 Alerts ON", callback_data="sub"),
         InlineKeyboardButton("🔕 Alerts OFF",callback_data="unsub")],
    ])

def back_kb(cb):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data=cb),
         InlineKeyboardButton("🏠 Home",    callback_data="home")],
        [InlineKeyboardButton("🚀 Open App", web_app=WebAppInfo(url=WEBAPP_URL))],
    ])

# ── MESSAGES ──
def msg_start():
    return (
        "<b>━━━━━━━━━━━━━━━━━━━━━━━━━━</b>\n"
        "🚀  <b>MR CRYPTO</b> — Premium Signal Bot\n"
        "<b>━━━━━━━━━━━━━━━━━━━━━━━━━━</b>\n\n"
        "Your professional crypto intelligence hub.\n\n"
        "⚡ <b>FEATURES</b>\n"
        "  ▸ Live prices for 15+ coins\n"
        "  ▸ Buy / Sell / Hold signals\n"
        "  ▸ RSI · SMA · MACD analysis\n"
        "  ▸ Fear &amp; Greed index\n"
        "  ▸ Trending coin tracker\n"
        "  ▸ Top gainers &amp; losers\n"
        "  ▸ Auto price spike alerts\n"
        "  ▸ Daily market report\n\n"
        "🎯 <b>Tap the button below to open\nthe full Trading Terminal App</b>\n\n"
        "<i>Data powered by CoinGecko</i>"
    )

def msg_market(coins, gdata, fg):
    btcd  = gdata.get("market_cap_percentage",{}).get("btc",0)
    ethd  = gdata.get("market_cap_percentage",{}).get("eth",0)
    tmc   = fb(gdata.get("total_market_cap",{}).get("usd",0))
    tvol  = fb(gdata.get("total_volume",{}).get("usd",0))
    mcc   = gdata.get("market_cap_change_percentage_24h_usd",0) or 0
    fv    = fg.get("value","?") if fg else "?"
    fcl   = fg.get("value_classification","?") if fg else "?"
    try: fi = int(fv); fmj = "😱" if fi<25 else "😨" if fi<45 else "😐" if fi<55 else "😊" if fi<75 else "🤑"
    except: fmj="😐"

    rows = ""
    for c in coins[:12]:
        sym  = COIN_META.get(c["id"],{}).get("sym",c.get("symbol","?").upper())
        pr   = fp(c.get("current_price",0))
        ch   = c.get("price_change_percentage_24h_in_currency",0) or 0
        sig,sc,_ = signal(c)
        arrow = "▲" if ch>=0 else "▼"
        rows += f"  {sig.split()[0]}  <b>{sym}</b>  <code>{pr}</code>  {arrow}{abs(ch):.2f}%\n"

    return (
        "<b>━━━━━━━━━━━━━━━━━━━━━━━━━━</b>\n"
        "🌍  <b>MARKET OVERVIEW</b>\n"
        "<b>━━━━━━━━━━━━━━━━━━━━━━━━━━</b>\n\n"
        f"📊 <b>Global Stats</b>\n"
        f"  Market Cap:  <code>{tmc}</code>  {fc(mcc)}\n"
        f"  24h Volume:  <code>{tvol}</code>\n"
        f"  BTC Dom:     <code>{btcd:.1f}%</code>\n"
        f"  ETH Dom:     <code>{ethd:.1f}%</code>\n\n"
        f"{fmj} <b>Fear &amp; Greed:</b> <code>{fv}/100</code> — <i>{fcl}</i>\n\n"
        "<b>━━━━━━━━━━━━━━━━━━━━━━━━━━</b>\n\n"
        "💹 <b>Live Prices</b>\n\n"
        f"{rows}\n"
        f"<i>🕐 {ts()}</i>"
    )

def msg_signal_coin(coin):
    sym  = COIN_META.get(coin["id"],{}).get("sym",coin.get("symbol","?").upper())
    name = coin.get("name","?")
    rank = coin.get("market_cap_rank","?")
    pr   = fp(coin.get("current_price",0))
    mc   = fb(coin.get("market_cap",0))
    vol  = fb(coin.get("total_volume",0))
    h24  = fp(coin.get("high_24h",0))
    l24  = fp(coin.get("low_24h",0))
    ath  = fp(coin.get("ath",0))
    athp = coin.get("ath_change_percentage",0) or 0
    ch1  = coin.get("price_change_percentage_1h_in_currency",0) or 0
    ch24 = coin.get("price_change_percentage_24h_in_currency",0) or 0
    ch7  = coin.get("price_change_percentage_7d_in_currency",0) or 0
    sig, sc, r = signal(coin)
    spark = coin.get("sparkline_in_7d",{}).get("price",[])
    s7  = sma(spark,49)
    s25 = sma(spark,168)
    rsi_bar = ""
    if r:
        filled = round(r/10)
        rsi_bar = "▓"*filled + "░"*(10-filled)
        rsi_zone = "Oversold 🟢" if r<30 else "Overbought 🔴" if r>70 else "Neutral 🟡"
    return (
        f"<b>━━━━━━━━━━━━━━━━━━━━━━━━━━</b>\n"
        f"<b>{name}</b>  ({sym})  #{rank}\n"
        f"<b>━━━━━━━━━━━━━━━━━━━━━━━━━━</b>\n\n"
        f"💰 <b>Price:</b>  <code>{pr}</code>\n"
        f"🎯 <b>Signal:</b>  <b>{sig}</b>\n"
        f"📊 <b>Score:</b>  {'+' if sc>=0 else ''}{sc}\n\n"
        f"<b>━━━━━━━━━━━━━━━━━━━━━━━━━━</b>\n\n"
        f"📈 <b>Performance</b>\n"
        f"  1h:  {fc(ch1)}\n"
        f"  24h: {fc(ch24)}\n"
        f"  7d:  {fc(ch7)}\n\n"
        f"📏 <b>24h Range</b>\n"
        f"  Low:  <code>{l24}</code>\n"
        f"  High: <code>{h24}</code>\n\n"
        f"🏔 <b>ATH:</b>  <code>{ath}</code>  ({athp:+.1f}%)\n\n"
        f"<b>━━━━━━━━━━━━━━━━━━━━━━━━━━</b>\n\n"
        f"🔬 <b>Indicators</b>\n"
        f"  RSI(14): <code>{r if r else '─'}</code>  [{rsi_bar}]  {rsi_zone if r else ''}\n"
        f"  SMA7:   <code>{fp(s7) if s7 else '─'}</code>\n"
        f"  SMA25:  <code>{fp(s25) if s25 else '─'}</code>\n\n"
        f"<b>━━━━━━━━━━━━━━━━━━━━━━━━━━</b>\n\n"
        f"🏦 <b>Market Data</b>\n"
        f"  Cap:    <code>{mc}</code>\n"
        f"  Volume: <code>{vol}</code>\n\n"
        f"<i>🕐 {ts()}\n⚠️ Not financial advice. DYOR.</i>"
    )

def msg_signals_all(coins):
    buys = []; holds = []; sells = []
    for c in coins:
        sig,sc,r = signal(c)
        sym = COIN_META.get(c["id"],{}).get("sym",c.get("symbol","?").upper())
        rstr = f"RSI:{r:.0f}" if r else "RSI:─"
        row = f"  {sig.split()[0]}  <b>{sym}</b>  <code>{fp(c.get('current_price',0))}</code>  ({rstr}  {'+' if sc>=0 else ''}{sc})\n"
        if "BUY" in sig:   buys.append(row)
        elif "SELL" in sig: sells.append(row)
        else:               holds.append(row)
    return (
        "<b>━━━━━━━━━━━━━━━━━━━━━━━━━━</b>\n"
        "🧠  <b>ALL SIGNALS DIGEST</b>\n"
        "<b>━━━━━━━━━━━━━━━━━━━━━━━━━━</b>\n\n"
        f"🟢 <b>BUY SIGNALS ({len(buys)})</b>\n"
        + ("".join(buys) if buys else "  None right now\n") +
        f"\n🟡 <b>HOLD ({len(holds)})</b>\n"
        + "".join(holds) +
        f"\n🔴 <b>SELL SIGNALS ({len(sells)})</b>\n"
        + ("".join(sells) if sells else "  None right now\n") +
        f"\n<i>🕐 {ts()}\n⚠️ Not financial advice. DYOR.</i>"
    )

def msg_trending(data):
    medals = ["🥇","🥈","🥉","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣"]
    rows = ""
    for i,item in enumerate(data[:8]):
        c = item.get("item",{})
        rows += f"  {medals[i] if i<len(medals) else str(i+1)+'.'} <b>{c.get('name','?')}</b> (<code>{c.get('symbol','?').upper()}</code>) — Rank #{c.get('market_cap_rank','?')}\n"
    return (
        "<b>━━━━━━━━━━━━━━━━━━━━━━━━━━</b>\n"
        "🔥  <b>TRENDING ON COINGECKO</b>\n"
        "<b>━━━━━━━━━━━━━━━━━━━━━━━━━━</b>\n\n"
        "Most searched coins last 24h:\n\n"
        + rows +
        f"\n<i>🕐 {ts()}</i>"
    )

def msg_fear(fg):
    val = int(fg.get("value",50)); cls = fg.get("value_classification","?")
    bar = "▓"*round(val/10) + "░"*(10-round(val/10))
    if val<25:   emoji,advice="😱","Extreme fear — historically strong BUY zone."
    elif val<45: emoji,advice="😨","Fear in market — consider DCA strategy."
    elif val<55: emoji,advice="😐","Neutral — wait for clearer direction."
    elif val<75: emoji,advice="😊","Greed present — manage risk carefully."
    else:        emoji,advice="🤑","Extreme greed — consider taking profits."
    return (
        "<b>━━━━━━━━━━━━━━━━━━━━━━━━━━</b>\n"
        f"{emoji}  <b>FEAR &amp; GREED INDEX</b>\n"
        "<b>━━━━━━━━━━━━━━━━━━━━━━━━━━</b>\n\n"
        f"  Score:  <b>{val}/100</b>\n"
        f"  Status: <i>{cls}</i>\n\n"
        f"  <code>[{bar}]</code>\n\n"
        f"💡 <b>Signal:</b> {advice}\n\n"
        "<b>Scale:</b>\n"
        "  0–24   😱 Extreme Fear\n"
        "  25–44  😨 Fear\n"
        "  45–55  😐 Neutral\n"
        "  56–75  😊 Greed\n"
        "  76–100 🤑 Extreme Greed\n\n"
        "<i>'Be fearful when others are greedy,\nand greedy when others are fearful.'\n— Warren Buffett</i>\n\n"
        f"<i>🕐 {ts()}</i>"
    )

def msg_top(coins):
    medals = ["🥇","🥈","🥉"] + [f"{i}." for i in range(4,16)]
    rows = ""
    for i,c in enumerate(coins[:15]):
        sym = COIN_META.get(c["id"],{}).get("sym",c.get("symbol","?").upper())
        ch  = c.get("price_change_percentage_24h_in_currency",0) or 0
        sig,sc,_ = signal(c)
        arrow = "▲" if ch>=0 else "▼"
        rows += f"  {medals[i] if i<len(medals) else str(i+1)+'.'} <b>{sym}</b>  <code>{fp(c.get('current_price',0))}</code>  {arrow}{abs(ch):.2f}%  {sig.split()[0]}\n"
    return (
        "<b>━━━━━━━━━━━━━━━━━━━━━━━━━━</b>\n"
        "🏆  <b>TOP 15 BY MARKET CAP</b>\n"
        "<b>━━━━━━━━━━━━━━━━━━━━━━━━━━</b>\n\n"
        + rows +
        f"\n<i>🕐 {ts()}</i>"
    )

def msg_movers(coins):
    srt = sorted(coins, key=lambda c: c.get("price_change_percentage_24h_in_currency",0) or 0, reverse=True)
    def row(c):
        sym = COIN_META.get(c["id"],{}).get("sym",c.get("symbol","?").upper())
        ch  = c.get("price_change_percentage_24h_in_currency",0) or 0
        return f"  <b>{sym}</b>  <code>{fp(c.get('current_price',0))}</code>  {fc(ch)}\n"
    return (
        "<b>━━━━━━━━━━━━━━━━━━━━━━━━━━</b>\n"
        "📊  <b>TOP GAINERS &amp; LOSERS</b>\n"
        "<b>━━━━━━━━━━━━━━━━━━━━━━━━━━</b>\n\n"
        "🟢 <b>TOP 5 GAINERS (24H)</b>\n"
        + "".join(row(c) for c in srt[:5]) +
        "\n🔴 <b>TOP 5 LOSERS (24H)</b>\n"
        + "".join(row(c) for c in srt[-5:][::-1]) +
        f"\n<i>🕐 {ts()}</i>"
    )

# ── COMMANDS ──
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    subscribers.add(update.effective_chat.id)
    await update.message.reply_text(msg_start(), parse_mode="HTML", reply_markup=main_kb())

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "<b>COMMANDS</b>\n\n"
        "/start — Main menu + App\n"
        "/market — Market overview\n"
        "/signal BTC — Coin signal\n"
        "/trending — Trending coins\n"
        "/top — Top 15 coins\n"
        "/movers — Gainers &amp; losers\n"
        "/fear — Fear &amp; Greed\n"
        "/alerts — Subscribe alerts\n",
        parse_mode="HTML", reply_markup=main_kb()
    )

async def cmd_market(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    m = await update.message.reply_text("⏳ Fetching data...")
    coins = await get_coins(TRACKED_COINS)
    gdata = (await get_global() or {}).get("data",{})
    fg    = (await get_fg() or {}).get("data",[{}])[0]
    if not coins: await m.edit_text("⚠️ API error. Try again."); return
    await m.edit_text(msg_market(coins,gdata,fg), parse_mode="HTML", reply_markup=back_kb("market"))

async def cmd_signal(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args: await update.message.reply_text("Usage: /signal BTC"); return
    sym   = ctx.args[0].upper()
    cid   = SYM_TO_ID.get(sym, sym.lower())
    m     = await update.message.reply_text(f"⏳ Analysing {sym}...")
    coins = await get_coins([cid])
    if not coins: await m.edit_text("⚠️ Coin not found."); return
    await m.edit_text(msg_signal_coin(coins[0]), parse_mode="HTML", reply_markup=back_kb(f"sig_{cid}"))

async def cmd_trending(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    m = await update.message.reply_text("⏳ Loading...")
    d = await get_trending()
    if not d: await m.edit_text("⚠️ API error."); return
    await m.edit_text(msg_trending(d.get("coins",[])), parse_mode="HTML", reply_markup=back_kb("trending"))

async def cmd_fear(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    d = await get_fg()
    fg = (d or {}).get("data",[{}])[0]
    await update.message.reply_text(msg_fear(fg), parse_mode="HTML", reply_markup=back_kb("fear"))

async def cmd_top(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    m = await update.message.reply_text("⏳ Loading...")
    coins = await get_coins(TRACKED_COINS)
    if not coins: await m.edit_text("⚠️ API error."); return
    await m.edit_text(msg_top(coins), parse_mode="HTML", reply_markup=back_kb("top"))

async def cmd_movers(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    m = await update.message.reply_text("⏳ Loading...")
    coins = await get_coins(TRACKED_COINS)
    if not coins: await m.edit_text("⚠️ API error."); return
    await m.edit_text(msg_movers(coins), parse_mode="HTML", reply_markup=back_kb("movers"))

async def cmd_alerts(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    subscribers.add(update.effective_chat.id)
    await update.message.reply_text(
        "<b>🔔 ALERTS ACTIVATED</b>\n\n"
        "You'll receive:\n"
        "  ⚡ Price spike alerts (±5% in 1h)\n"
        "  📡 RSI signal alerts every 15 min\n"
        "  🌅 Daily report at 09:00 UTC",
        parse_mode="HTML"
    )

# ── CALLBACKS ──
async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer(); d = q.data
    async def edit(text, kb=None): await q.edit_message_text(text, parse_mode="HTML", reply_markup=kb or back_kb(d))

    if d == "home":
        await q.edit_message_text(msg_start(), parse_mode="HTML", reply_markup=main_kb())
    elif d == "market":
        await edit("⏳ Fetching...")
        coins = await get_coins(TRACKED_COINS)
        gdata = (await get_global() or {}).get("data",{})
        fg    = (await get_fg() or {}).get("data",[{}])[0]
        if coins: await edit(msg_market(coins,gdata,fg), back_kb("market"))
    elif d == "signals":
        await edit("⏳ Computing...")
        coins = await get_coins(TRACKED_COINS)
        if coins: await edit(msg_signals_all(coins), back_kb("signals"))
    elif d == "trending":
        await edit("⏳ Loading...")
        data = await get_trending()
        if data: await edit(msg_trending(data.get("coins",[])), back_kb("trending"))
    elif d == "fear":
        await edit("⏳ Loading...")
        data = await get_fg()
        fg = (data or {}).get("data",[{}])[0]
        await edit(msg_fear(fg), back_kb("fear"))
    elif d == "top":
        await edit("⏳ Loading...")
        coins = await get_coins(TRACKED_COINS)
        if coins: await edit(msg_top(coins), back_kb("top"))
    elif d == "movers":
        await edit("⏳ Loading...")
        coins = await get_coins(TRACKED_COINS)
        if coins: await edit(msg_movers(coins), back_kb("movers"))
    elif d.startswith("sig_"):
        cid = d[4:]
        await edit("⏳ Analysing...")
        coins = await get_coins([cid])
        if coins: await edit(msg_signal_coin(coins[0]), back_kb(d))
    elif d == "sub":
        subscribers.add(q.from_user.id); await q.answer("🔔 Subscribed!", show_alert=True)
    elif d == "unsub":
        subscribers.discard(q.from_user.id); await q.answer("🔕 Unsubscribed.", show_alert=True)

# ── JOBS ──
async def job_alerts(ctx: ContextTypes.DEFAULT_TYPE):
    if not subscribers: return
    coins = await get_coins(TRACKED_COINS)
    if not coins: return
    for c in coins:
        ch1 = c.get("price_change_percentage_1h_in_currency",0) or 0
        if abs(ch1) >= 5.0:
            sym = COIN_META.get(c["id"],{}).get("sym",c.get("symbol","?").upper())
            sig,sc,_ = signal(c)
            direction = "🚀 PUMP" if ch1>0 else "💥 DUMP"
            text = (
                f"<b>⚡ ALERT — {direction}</b>\n\n"
                f"<b>{sym}</b> moved {fc(ch1)} in 1 hour!\n"
                f"Price: <code>{fp(c.get('current_price',0))}</code>\n"
                f"Signal: <b>{sig}</b>\n\n"
                f"<i>{ts()}</i>"
            )
            for uid in subscribers:
                try: await ctx.bot.send_message(uid, text, parse_mode="HTML")
                except: pass

async def job_daily(ctx: ContextTypes.DEFAULT_TYPE):
    if not subscribers: return
    coins = await get_coins(TRACKED_COINS)
    gdata = (await get_global() or {}).get("data",{})
    fg    = (await get_fg() or {}).get("data",[{}])[0]
    if not coins: return
    text = "🌅 <b>DAILY MARKET REPORT</b>\n\n" + msg_market(coins,gdata,fg)
    for uid in subscribers:
        try: await ctx.bot.send_message(uid, text, parse_mode="HTML")
        except: pass

# ── MAIN ──
async def post_init(app):
    await app.bot.set_my_commands([
        BotCommand("start",    "Main menu + Trading App"),
        BotCommand("market",   "Live market overview"),
        BotCommand("signal",   "Coin signal e.g. /signal BTC"),
        BotCommand("trending", "Trending coins"),
        BotCommand("top",      "Top 15 by market cap"),
        BotCommand("movers",   "Gainers & losers"),
        BotCommand("fear",     "Fear & Greed Index"),
        BotCommand("alerts",   "Subscribe to alerts"),
        BotCommand("help",     "Help"),
    ])

def main():
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ Set BOT_TOKEN"); return
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    for cmd,fn in [("start",cmd_start),("help",cmd_help),("market",cmd_market),
                   ("signal",cmd_signal),("trending",cmd_trending),("fear",cmd_fear),
                   ("top",cmd_top),("movers",cmd_movers),("alerts",cmd_alerts)]:
        app.add_handler(CommandHandler(cmd,fn))
    app.add_handler(CallbackQueryHandler(on_button))
    jq = app.job_queue
    jq.run_repeating(job_alerts, interval=CHECK_INTERVAL, first=60)
    jq.run_daily(job_daily, time=datetime.strptime("09:00","%H:%M").time())
    print("🚀 MR CRYPTO Bot v3.0 — Running...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
