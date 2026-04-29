import disnake
import os
import requests
from disnake.ext import commands
from pymongo import MongoClient

# --- CONFIGURATION ---
MONGO_URL = os.getenv("MONGO_URL")
RIOT_TOKEN = os.getenv("RIOT_TOKEN")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", 0))

client = MongoClient(MONGO_URL)
db = client['rank_bot']
players_col = db['players']

bot = commands.InteractionBot()

RANK_VALUES = {
    "Iron": 100, "Bronze": 400, "Silver": 700, "Gold": 1000, 
    "Platinum": 1300, "Emerald": 1600, "Diamond": 1900, 
    "Master": 2200, "Grandmaster": 2500, "Challenger": 2800, "Unranked": 0
}

def get_rank_info(rank_str):
    for tier in RANK_VALUES.keys():
        if tier in rank_str:
            pts = RANK_VALUES[tier]
            if "I" in rank_str and "II" not in rank_str: pts += 75
            elif "II" in rank_str: pts += 50
            elif "III" in rank_str: pts += 25
            return pts
    return 0

# --- RÉCUPÉRATION DONNÉES ---

def get_valo_data(name, tag):
    try:
        url = f"https://api.henrikdev.xyz/valorant/v1/mmr/eu/{name}/{tag}"
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            data = r.json().get('data')
            if data and 'currenttierpatched' in data:
                rank = data['currenttierpatched']
                return {"rank": rank, "pts": get_rank_info(rank)}
        print(f"❓ Valo: {name}#{tag} -> Status {r.status_code}")
    except Exception as e:
        print(f"❌ Erreur Valo {name}: {e}")
    return {"rank": "Unranked", "pts": 0}

def get_lol_data(name, tag):
    try:
        # 1. Account V1 (PUUID)
        acc_url = f"https://europe.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{name}/{tag}?api_key={RIOT_TOKEN}"
        r_acc = requests.get(acc_url, timeout=5)
        if r_acc.status_code != 200:
            print(f"❓ LoL Account: {name}#{tag} -> {r_acc.status_code} (Vérifie ta clé Riot !)")
            return {"rank": "Unranked", "pts": 0}
        
        puuid = r_acc.json().get('puuid')
        
        # 2. Summoner V4 (ID)
        sum_url = f"https://euw1.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{puuid}?api_key={RIOT_TOKEN}"
        r_sum = requests.get(sum_url, timeout=5).json()
        
        # 3. League V4 (Rangs)
        league_url = f"https://euw1.api.riotgames.com/lol/league/v4/entries/by-summoner/{r_sum['id']}?api_key={RIOT_TOKEN}"
        leagues = requests.get(league_url, timeout=5).json()
        
        for l in leagues:
            if l['queueType'] == 'RANKED_SOLO_5x5':
                rank = f"{l['tier'].capitalize()} {l['rank']}"
                return {"rank": rank, "pts": get_rank_info(rank)}
    except Exception as e:
        print(f"❌ Erreur LoL {name}: {e}")
    return {"rank": "Unranked", "pts": 0}

# --- INTERFACE ---

class LeaderboardView(disnake.ui.View):
    def __init__(self, data):
        super().__init__(timeout=None)
        self.data = data

    def create_embed(self, sorted_data, title, game_focus):
        embed = disnake.Embed(title=title, color=0xFFAA00)
        col_players = ""
        col_ranks = ""
        
        for i, p in enumerate(sorted_data[:15]):
            medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else f"**{i+1}.**"
            col_players += f"{medal} {p['name']}\n"
            
            v_txt = f"`{p['v_rank']}`" if game_focus in ["valo", "both"] else ""
            l_txt = f"`{p['l_rank']}`" if game_focus in ["lol", "both"] else ""
            
            if game_focus == "both":
                col_ranks += f"🔴 {v_txt} | 🔵 {l_txt}\n"
            else:
                col_ranks += f"{v_txt if game_focus == 'valo' else l_txt}\n"

        embed.add_field(name="Joueurs", value=col_players, inline=True)
        embed.add_field(name="Rangs", value=col_ranks, inline=True)
        return embed

    @disnake.ui.button(label="Global", emoji="🌍", style=disnake.ButtonStyle.secondary)
    async def sort_global(self, button, inter):
        sorted_data = sorted(self.data, key=lambda x: x['total_pts'], reverse=True)
        await inter.response.edit_message(embed=self.create_embed(sorted_data, "Classement Global", "both"))

    @disnake.ui.button(label="Valorant", emoji="🔫", style=disnake.ButtonStyle.danger)
    async def sort_valo(self, button, inter):
        sorted_data = sorted(self.data, key=lambda x: x['v_pts'], reverse=True)
        await inter.response.edit_message(embed=self.create_embed(sorted_data, "Classement Valorant", "valo"))

    @disnake.ui.button(label="LoL", emoji="⚔️", style=disnake.ButtonStyle.primary)
    async def sort_lol(self, button, inter):
        sorted_data = sorted(self.data, key=lambda x: x['l_pts'], reverse=True)
        await inter.response.edit_message(embed=self.create_embed(sorted_data, "Classement League", "lol"))

async def refresh_leaderboard():
    channel = bot.get_channel(CHANNEL_ID)
    if not channel: return
    async for m in channel.history(limit=5):
        if m.author == bot.user: await m.delete()

    players = list(players_col.find())
    all_data = []
    for p in players:
        v = get_valo_data(p['name'], p['tag'])
        l = get_lol_data(p['name'], p['tag'])
        all_data.append({
            "name": p['name'], "v_rank": v['rank'], "v_pts": v['pts'],
            "l_rank": l['rank'], "l_pts": l['pts'],
            "total_pts": v['pts'] + l['pts']
        })

    if all_data:
        all_data.sort(key=lambda x: x['total_pts'], reverse=True)
        await channel.send(embed=LeaderboardView(all_data).create_embed(all_data, "Classement Global", "both"), view=LeaderboardView(all_data))

@bot.event
async def on_ready():
    print(f"✅ Bot prêt"); await refresh_leaderboard()

@bot.slash_command(name="add")
async def add(inter, riot_id: str):
    if not inter.author.guild_permissions.administrator: return
    name, tag = riot_id.split("#")
    players_col.update_one({"name": name, "tag": tag}, {"$set": {"name": name, "tag": tag}}, upsert=True)
    await inter.response.send_message("✅", ephemeral=True); await refresh_leaderboard()

bot.run(DISCORD_TOKEN)
