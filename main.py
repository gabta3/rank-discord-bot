import disnake
import os
from disnake.ext import commands, tasks
from pymongo import MongoClient
import requests
from PIL import Image, ImageDraw
import io

# --- CONFIGURATION VIA VARIABLES D'ENVIRONNEMENT ---
MONGO_URL = os.getenv("MONGO_URL")
RIOT_TOKEN = os.getenv("RIOT_TOKEN")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID_STR = os.getenv("CHANNEL_ID", "0")
CHANNEL_ID = int(CHANNEL_ID_STR) if CHANNEL_ID_STR.isdigit() else 0

client = MongoClient(MONGO_URL)
db = client['rank_bot']
players_col = db['players']

bot = commands.InteractionBot()

def get_image_from_url(url):
    if not url: return None
    response = requests.get(url)
    return Image.open(io.BytesIO(response.content)).convert("RGBA")

def get_valo_data(name, tag):
    url = f"https://api.henrikdev.xyz/valorant/v1/mmr/eu/{name}/{tag}"
    r = requests.get(url)
    if r.status_code == 200:
        data = r.json()['data']
        return {"rank": data['currenttierpatched'], "icon_url": data['images']['small']}
    return {"rank": "Unranked", "icon_url": None}

def get_lol_data(name, tag):
    try:
        acc_url = f"https://europe.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{name}/{tag}?api_key={RIOT_TOKEN}"
        r = requests.get(acc_url)
        if r.status_code != 200: 
            print(f"⚠️ LoL: Joueur {name}#{tag} introuvable (Code {r.status_code})")
            return {"rank": "Non trouvé", "icon_url": None}
        
        puuid = r.json().get('puuid')
        if not puuid: return {"rank": "Erreur ID", "icon_url": None}

        sum_url = f"https://euw1.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{puuid}?api_key={RIOT_TOKEN}"
        r_sum = requests.get(sum_url)
        if r_sum.status_code != 200: return {"rank": "Unranked", "icon_url": None}
        sum_data = r_sum.json()
        
        league_url = f"https://euw1.api.riotgames.com/lol/league/v4/entries/by-summoner/{sum_data['id']}?api_key={RIOT_TOKEN}"
        leagues = requests.get(league_url).json()
        
        for l in leagues:
            if l['queueType'] == 'RANKED_SOLO_5x5':
                tier = l['tier'].capitalize()
                icon_url = f"https://raw.communitydragon.org/latest/plugins/rcp-fe-lol-static-assets/global/default/images/ranked-emblems/emblem-{tier.lower()}.png"
                return {"rank": f"{tier} {l['rank']}", "icon_url": icon_url}
        
        return {"rank": "Unranked", "icon_url": None}
    except Exception as e:
        print(f"❌ Erreur LoL pour {name}: {e}")
        return {"rank": "Erreur API", "icon_url": None}

def generate_leaderboard_img(players_data):
    width, row_h = 1000, 70
    height = 120 + (max(1, len(players_data)) * row_h)
    img = Image.new('RGB', (width, height), color=(15, 18, 22))
    draw = ImageDraw.Draw(img)
    draw.text((50, 40), "JOUEUR", fill="white")
    draw.text((400, 40), "VALORANT", fill="#ff4655")
    draw.text((700, 40), "LEAGUE OF LEGENDS", fill="#00cfef")
    draw.line([(50, 85), (950, 85)], fill="gray", width=1)
    for i, p in enumerate(players_data):
        y = 110 + (i * row_h)
        draw.text((50, y + 15), f"{p['name']}#{p['tag']}", fill="white")
        if p['valo_icon']:
            icon = get_image_from_url(p['valo_icon']).resize((40, 40))
            img.paste(icon, (400, y + 5), icon)
        draw.text((455, y + 15), p['valo_rank'], fill="lightgray")
        if p['lol_icon']:
            icon = get_image_from_url(p['lol_icon']).resize((40, 40))
            img.paste(icon, (700, y + 5), icon)
        draw.text((755, y + 15), p['lol_rank'], fill="lightgray")
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='PNG')
    img_byte_arr.seek(0)
    return img_byte_arr

@bot.event
async def on_ready():
    print(f"✅ Bot prêt : {bot.user}")
    update_leaderboard.start()

@bot.slash_command(name="add")
async def add(inter, riot_id: str):
    if "#" not in riot_id:
        return await inter.response.send_message("Format requis: Nom#Tag", ephemeral=True)
    name, tag = riot_id.split("#")
    players_col.update_one({"name": name, "tag": tag}, {"$set": {"name": name, "tag": tag}}, upsert=True)
    await inter.response.send_message(f"✅ {name}#{tag} ajouté !")

@tasks.loop(hours=12)
async def update_leaderboard():
    channel = bot.get_channel(CHANNEL_ID)
    if not channel: return
    players = list(players_col.find())
    all_data = []
    for p in players:
        v = get_valo_data(p['name'], p['tag'])
        l = get_lol_data(p['name'], p['tag'])
        all_data.append({
            "name": p['name'], "tag": p['tag'],
            "valo_rank": v['rank'], "valo_icon": v['icon_url'],
            "lol_rank": l['rank'], "lol_icon": l['icon_url']
        })
    if all_data:
        img = generate_leaderboard_img(all_data)
        await channel.send(file=disnake.File(img, "leaderboard.png"))

bot.run(DISCORD_TOKEN)
