import discord
import os
import asyncio
import requests
from datetime import datetime, timezone
from requests.auth import HTTPBasicAuth  # <-- import this

# ===== ENV VARS =====
TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
RACING_API_USERNAME = os.getenv("RACING_API_USERNAME")
RACING_API_PASSWORD = os.getenv("RACING_API_PASSWORD")

# ===== CONFIG =====
REGION = "au"
MIN_EV = 0.03
MAX_HOURS_TO_START = 24
CHECK_INTERVAL = 900

TRUSTED_BOOKS = ["TAB", "Sportsbet", "PointsBet", "Neds", "Betfair AU"]

intents = discord.Intents.default()
client = discord.Client(intents=intents)

posted_bets = set()
last_odds = {}

def calc_ev(book_odds, true_prob):
    return (book_odds * true_prob) - 1

def staking_units(ev):
    if ev >= 0.12:
        return 3.0
    elif ev >= 0.08:
        return 2.0
    elif ev >= 0.05:
        return 1.0
    return 0.5

def hours_until_start(start_time):
    start = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    return (start - now).total_seconds() / 3600

async def check_races(channel):
    url = f"https://api.racingapi.com.au/v1/races/upcoming?region={REGION}"

    try:
        res = requests.get(url, auth=HTTPBasicAuth(RACING_API_USERNAME, RACING_API_PASSWORD), timeout=10)
        if res.status_code != 200:
            print(f"Racing API error: {res.status_code}")
            return
        races = res.json()
    except Exception as e:
        print(f"Error fetching races: {e}")
        return

    for race in races:
        race_id = race["race_id"]
        race_name = race["race_name"]
        start_time = race["start_time"]
        hrs_to_start = hours_until_start(start_time)
        if hrs_to_start > MAX_HOURS_TO_START:
            continue

        horses = race.get("horses", [])
        bookmakers = race.get("bookmakers", [])

        if len(bookmakers) < 2:
            continue

        for horse in horses:
            horse_name = horse["name"]

            ref_prices = []
            for b in bookmakers:
                if b["name"] in TRUSTED_BOOKS:
                    try:
                        price = next(h["price"] for h in b["odds"] if h["horse"] == horse_name)
                        ref_prices.append(price)
                    except:
                        continue

            if len(ref_prices) < 2:
                continue

            true_prob = sum(1/p for p in ref_prices)/len(ref_prices)
            if max(ref_prices)/min(ref_prices) > 1.15:
                continue

            best_price = 0
            best_book = None
            supplementary = []
            line_movement_note = ""

            for b in bookmakers:
                try:
                    price = next(h["price"] for h in b["odds"] if h["horse"] == horse_name)
                    key = f"{race_id}-{horse_name}-{b['name']}"
                    prev_price = last_odds.get(key)
                    if prev_price and prev_price != price:
                        line_movement_note += f"📈 {b['name']} moved: {prev_price} → {price}\n"
                    last_odds[key] = price

                    if price > best_price:
                        if best_book:
                            supplementary.append((best_book["name"], best_price))
                        best_price = price
                        best_book = b
                    else:
                        supplementary.append((b["name"], price))
                except:
                    continue

            ev = calc_ev(best_price, true_prob)
            if ev < MIN_EV:
                continue

            bet_key = f"{race_id}-{horse_name}"
            if bet_key in posted_bets:
                continue

            units = staking_units(ev)
            if units <= 0:
                continue

            posted_bets.add(bet_key)

            sup_text = ""
            for book, price in sorted(supplementary, key=lambda x: -x[1])[:4]:
                sup_text += f"• {book}: {price}\n"

            msg = (
                f"🏇 **+EV BET** 🏇\n\n"
                f"Race: {race_name}\n"
                f"Horse: **{horse_name}**\n\n"
                f"🏆 **Best Odds:** {best_price} ({best_book['name']})\n"
                f"📊 **EV:** {round(ev*100,2)}%\n"
                f"📈 **Stake:** {units} units\n"
                f"⏱ Starts in: {round(hrs_to_start,1)}h\n\n"
                f"{line_movement_note}"
                f"📚 **Other Books:**\n{sup_text}"
            )

            await channel.send(msg)

async def ev_loop():
    await client.wait_until_ready()
    channel = client.get_channel(CHANNEL_ID)
    while True:
        await check_races(channel)
        await asyncio.sleep(CHECK_INTERVAL)

@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    client.loop.create_task(ev_loop())

client.run(TOKEN)
