import discord
import os
import asyncio
import requests
from datetime import datetime, timedelta
import pytz

# ---------- ENVIRONMENT VARIABLES ----------
TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
API_KEY = os.getenv("RACING_API_KEY")
MIN_EV = float(os.getenv("MIN_EV", 0.05))
MAX_LOOKAHEAD_HOURS = int(os.getenv("MAX_LOOKAHEAD_HOURS", 24))
KELLY_FRACTION = float(os.getenv("KELLY_FRACTION", 0.1))

# ---------- TIMEZONE ----------
AU_TZ = pytz.timezone("Australia/Sydney")

# ---------- Discord Setup ----------
intents = discord.Intents.default()
client = discord.Client(intents=intents)

# ---------- TRACK POSTED BETS ----------
posted_bets = {}  # structure: {race_id: {horse_id: True}}

# ---------- UTILITY FUNCTIONS ----------
def calc_ev(book_odds, ref_odds):
    true_prob = 1 / ref_odds
    return (book_odds * true_prob) - 1

def kelly_units(ev, book_odds):
    b = book_odds - 1
    q = 1 - ev
    kelly = ((ev * b) - q) / b if b > 0 else 0
    stake = max(kelly * KELLY_FRACTION, 0.5)
    return round(stake, 2)

def within_time_limit(race_time):
    now = datetime.now(AU_TZ)
    return now <= race_time <= now + timedelta(hours=MAX_LOOKAHEAD_HOURS)

# ---------- MAIN EV CHECK FUNCTION ----------
async def check_races(channel):
    url = f"https://api.example.com/au/racing/odds?apiKey={API_KEY}&format=json"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code != 200:
            print("Racing API error", response.status_code)
            return
        races = response.json()
    except Exception as e:
        print("Error fetching races:", e)
        return

    for race in races:
        race_id = race["id"]
        race_name = race["name"]
        race_time_str = race["start_time"]  # e.g. ISO format
        race_time = AU_TZ.localize(datetime.fromisoformat(race_time_str))

        if not within_time_limit(race_time):
            continue  # skip races outside lookahead

        horses = race["horses"]  # list of horses
        # Example: each horse = {"id":..., "name":..., "odds": {"book1": 5.5, "book2": 5.2,...}}

        for horse in horses:
            horse_id = horse["id"]
            horse_name = horse["name"]
            odds_dict = horse["odds"]

            # Skip already posted bets
            if posted_bets.get(race_id, {}).get(horse_id):
                continue

            # Determine highest odds & reference odds
            sorted_books = sorted(odds_dict.items(), key=lambda x: x[1], reverse=True)
            if not sorted_books:
                continue
            best_book, best_odds = sorted_books[0]

            # reference odds = average of other books
            other_odds = [v for k, v in sorted_books[1:]] or [best_odds]
            ref_odds = sum(other_odds) / len(other_odds)

            ev = calc_ev(best_odds, ref_odds)
            if ev < MIN_EV:
                continue

            stake = kelly_units(ev, best_odds)

            # format supplementary bookmakers
            supplementary = "\n".join([f"- {k}: {v}" for k, v in sorted_books[1:]])

            # send message
            msg = (
                f"🏇 **{race_name}** ({race_time.strftime('%d/%m %H:%M')})\n"
                f"🐎 {horse_name}\n"
                f"📍 Best Book: {best_book}\n"
                f"💰 Odds: {best_odds}\n"
                f"📊 EV: {round(ev*100,2)}%\n"
                f"📈 Stake: {stake} Units\n"
            )
            if supplementary:
                msg += f"\nOther books:\n{supplimentary}"

            await channel.send(msg)

            # mark as posted
            if race_id not in posted_bets:
                posted_bets[race_id] = {}
            posted_bets[race_id][horse_id] = True

# ---------- BOT LOOP ----------
@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    client.loop.create_task(racing_loop())

async def racing_loop():
    await client.wait_until_ready()
    channel = client.get_channel(CHANNEL_ID)
    while True:
        await check_races(channel)
        await asyncio.sleep(900)  # check every 15 min

client.run(TOKEN)
