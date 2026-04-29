import disnake
import os
import io
import requests
from disnake.ext import commands, tasks
from pymongo import MongoClient
from PIL import Image, ImageDraw, ImageFont

# --- CONFIGURATION ---
MONGO_URL = os.getenv("MONGO_URL")
RIOT_TOKEN = os.getenv("RIOT_TOKEN")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", 0))

client = MongoClient(MONGO_URL)
db = client['rank_bot']
players_col = db['players']

bot = commands.InteractionBot()

# --- FONCTIONS API ---

def get_image_from_url(url):
    try:
        if not url: return None
        response = requests.get(url, timeout=5)
        return Image.open(io.BytesIO(response.content)).convert("RGBA")
    except: return None

def get_valo_data(name, tag):
    try:
        url = f"https://api.henrikdev.xyz/valorant/v1/mmr/eu/{name}/{tag}"
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            data = r.json()['data']
            return {"rank": data['currenttierpatched'], "icon_url": data['images']['small']}
        return {"rank": "Unranked", "icon_url": None}
    except: return {"rank": "Erreur API", "icon_url": None}

def get_lol_data(name, tag):
    try:
        acc_url = f"https://europe.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{name}/{tag}?api_key={RIOT_TOKEN}"
        r = requests.get(acc_url, timeout=5)
        if r.status_code != 200: return {"rank": "Non trouvé", "icon_url": None}
        puuid = r.json().get('puuid')
        
        sum_url = f"https://euw1.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{puuid}?api_key={RIOT_TOKEN}"
        r_sum = requests.get(sum_url, timeout=5).json()
        
        league_url = f"https://euw1.api.riotgames.com/lol/league/v4/entries/by-summoner/{r_sum['id']}?api_key={RIOT_TOKEN}"
        leagues = requests.get(league_url, timeout=5).json()
        
        for l in leagues:
            if l['queueType'] == 'RANKED_SOLO_5x5':
                tier = l['tier'].capitalize()
                icon_url = f"https://raw.communitydragon.org/latest/plugins/rcp-fe-lol-static-assets/global/default/images/ranked-emblems/emblem-{tier.lower()}.png"
                return {"rank": f"{tier} {l['rank']}", "icon_url": icon_url}
        return {"rank": "Unranked", "icon_url": None}
    except: return {"rank": "Erreur API", "icon_url": None}

# --- GÉNÉRATION D'IMAGE ---

def generate_leaderboard_img(players_data):
    width, row_h = 1000, 80
    height = 150 + (max(1, len(players_data)) * row_h)
    img = Image.new('RGB', (width, height), color=(15, 18, 22))
    draw = ImageDraw.Draw(img)
    
    # Header
    draw.text((50, 40), "JOUEUR", fill="white")
    draw.text((400, 40), "VALORANT", fill="#ff4655")
    draw.text((700, 40), "LEAGUE OF LEGENDS", fill="#00cfef")
    draw.line([(50, 95), (950, 95)], fill="gray", width=2)

    for i, p in enumerate(players_data):
        y = 120 + (i * row_h)
        draw.text((50, y + 20), f"{p['name']}#{p['tag']}", fill="white")
        
        # Valo
        if p['valo_icon']:
            icon = get_image_from_url(p['valo_icon'])
            if icon: img.paste(icon.resize((50, 50)), (400, y), icon.resize((50, 50)))
        draw.text((460, y + 20), p['valo_rank'], fill="lightgray")
        
        # LoL
        if p['lol_icon']:
            icon = get_image_from_url(p['lol_icon'])
            if icon: img.paste(icon.resize((50, 50)), (700, y), icon.resize((50, 50)))
        draw.text((760, y + 20), p['lol_rank'], fill="lightgray")

    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='PNG')
    img_byte_arr.seek(0)
    return img_byte_arr

# --- COMMANDES ---

@bot.event
async def on_ready():
    print(f"✅ Bot opérationnel : {bot.user}")
    update_leaderboard.start()

# Filtre pour vérifier le salon et les permissions Admin
async def check_permissions(inter):
    if inter.channel_id != CHANNEL_ID:
        await inter.response.send_message(f"❌ Utilise le salon <#{CHANNEL_ID}> !", ephemeral=True)
        return False
    if not inter.author.guild_permissions.administrator:
        await inter.response.send_message("⛔ Seul un admin peut faire ça.", ephemeral=True)
        return False
    return True

@bot.slash_command(name="add")
async def add(inter, riot_id: str):
    if not await check_permissions(inter): return
    if "#" not in riot_id:
        return await inter.response.send_message("Format: Nom#Tag", ephemeral=True)
    
    name, tag = riot_id.split("#")
    players_col.update_one({"name": name, "tag": tag}, {"$set": {"name": name, "tag": tag}}, upsert=True)
    await inter.response.send_message(f"✅ **{riot_id}** ajouté !", delete_after=5)

@bot.slash_command(name="del")
async def delete(inter, riot_id: str):
    if not await check_permissions(inter): return
    name, tag = riot_id.split("#")
    players_col.delete_one({"name": name, "tag": tag})
    await inter.response.send_message(f"🗑️ **{riot_id}** supprimé.", delete_after=5)

@bot.slash_command(name="refresh")
async def refresh(inter):
    if not await check_permissions(inter): return
    await inter.response.send_message("🔄 Actualisation...", delete_after=3)
    await update_leaderboard()

@tasks.loop(hours=12)
async def update_leaderboard():
    channel = bot.get_channel(CHANNEL_ID)
    if not channel: return
    
    # Nettoyage des anciens messages du bot dans le salon pour ne garder que le dernier
    async for message in channel.history(limit=20):
        if message.author == bot.user:
            await message.delete()

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
