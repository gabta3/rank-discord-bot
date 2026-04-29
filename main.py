import disnake
import os
import requests
from disnake.ext import commands, tasks
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

# --- LOGIQUE DE POINTS (MMR) ---
# Système de points pour classer les joueurs entre eux
RANK_POINTS = {
    "Iron": 100, "Bronze": 400, "Silver": 700, "Gold": 1000, 
    "Platinum": 1300, "Emerald": 1600, "Diamond": 1900, 
    "Master": 2200, "Grandmaster": 2500, "Challenger": 2800, "Unranked": 0
}

def calculate_score(rank_str):
    if not rank_str or "Unranked" in rank_str: return 0
    for tier, pts in RANK_POINTS.items():
        if tier in rank_str:
            bonus = 0
            if "I" in rank_str and "II" not in rank_str: bonus = 75
            elif "II" in rank_str: bonus = 50
            elif "III" in rank_str: bonus = 25
            return pts + bonus
    return 0

# --- RÉCUPÉRATION DES DONNÉES ---

def get_valo_data(name, tag):
    try:
        r = requests.get(f"https://api.henrikdev.xyz/valorant/v1/mmr/eu/{name}/{tag}", timeout=5)
        if r.status_code == 200:
            data = r.json()['data']
            rank = data['currenttierpatched']
            return {"rank": rank, "pts": calculate_score(rank)}
    except: pass
    return {"rank": "Unranked", "pts": 0}

def get_lol_data(name, tag):
    try:
        acc = requests.get(f"https://europe.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{name}/{tag}?api_key={RIOT_TOKEN}", timeout=5).json()
        puuid = acc['puuid']
        sum_data = requests.get(f"https://euw1.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{puuid}?api_key={RIOT_TOKEN}", timeout=5).json()
        leagues = requests.get(f"https://euw1.api.riotgames.com/lol/league/v4/entries/by-summoner/{sum_data['id']}?api_key={RIOT_TOKEN}", timeout=5).json()
        for l in leagues:
            if l['queueType'] == 'RANKED_SOLO_5x5':
                rank = f"{l['tier'].capitalize()} {l['rank']}"
                return {"rank": rank, "pts": calculate_score(rank)}
    except: pass
    return {"rank": "Unranked", "pts": 0}

# --- SYSTÈME DE BOUTONS ---

class LeaderboardView(disnake.ui.View):
    def __init__(self, data):
        super().__init__(timeout=None)
        self.data = data

    def create_embed(self, sorted_data, title):
        embed = disnake.Embed(title=title, color=0x2b2d31)
        header = "👤 **Joueur** | 🔴 **Valo** | 🔵 **LoL** | 🏆 **Total**\n"
        header += "⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n"
        
        description = ""
        for i, p in enumerate(sorted_data):
            medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else "🔹"
            description += f"{medal} **{p['name']}** | `{p['v_rank']}` | `{p['l_rank']}` | **{p['total']}**\n"
        
        embed.description = header + description
        embed.set_footer(text="Clique sur les boutons pour changer le mode de tri")
        return embed

    @disnake.ui.button(label="Global", emoji="🌍", style=disnake.ButtonStyle.secondary)
    async def sort_global(self, button, inter):
        sorted_data = sorted(self.data, key=lambda x: x['total'], reverse=True)
        await inter.response.edit_message(embed=self.create_embed(sorted_data, "🏆 Classement Général (MMR Combiné)"))

    @disnake.ui.button(label="Valorant", emoji="🔫", style=disnake.ButtonStyle.danger)
    async def sort_valo(self, button, inter):
        sorted_data = sorted(self.data, key=lambda x: x['v_pts'], reverse=True)
        await inter.response.edit_message(embed=self.create_embed(sorted_data, "🔴 Classement Valorant"))

    @disnake.ui.button(label="LoL", emoji="⚔️", style=disnake.ButtonStyle.primary)
    async def sort_lol(self, button, inter):
        sorted_data = sorted(self.data, key=lambda x: x['l_pts'], reverse=True)
        await inter.response.edit_message(embed=self.create_embed(sorted_data, "🔵 Classement League of Legends"))

# --- TÂCHES ET COMMANDES ---

async def refresh_leaderboard():
    channel = bot.get_channel(CHANNEL_ID)
    if not channel: return

    # Supprimer les anciens messages du bot pour garder le salon propre
    async for msg in channel.history(limit=5):
        if msg.author == bot.user:
            await msg.delete()

    players = list(players_col.find())
    all_data = []
    for p in players:
        v = get_valo_data(p['name'], p['tag'])
        l = get_lol_data(p['name'], p['tag'])
        all_data.append({
            "name": f"{p['name']}#{p['tag']}", 
            "v_rank": v['rank'], "v_pts": v['pts'],
            "l_rank": l['rank'], "l_pts": l['pts'], 
            "total": v['pts'] + l['pts']
        })

    if all_data:
        all_data.sort(key=lambda x: x['total'], reverse=True)
        view = LeaderboardView(all_data)
        await channel.send(embed=view.create_embed(all_data, "🏆 Classement Général (MMR Combiné)"), view=view)

@bot.event
async def on_ready():
    print(f"✅ Bot prêt : {bot.user}")
    await refresh_leaderboard()

@bot.slash_command(name="add", description="Ajoute un joueur au classement")
async def add(inter, riot_id: str):
    if not inter.author.guild_permissions.administrator:
        return await inter.response.send_message("❌ Admin seulement.", ephemeral=True)
    
    if "#" not in riot_id:
        return await inter.response.send_message("Format: Nom#Tag", ephemeral=True)
    
    name, tag = riot_id.split("#")
    players_col.update_one({"name": name, "tag": tag}, {"$set": {"name": name, "tag": tag}}, upsert=True)
    await inter.response.send_message(f"✅ Joueur {riot_id} ajouté !", ephemeral=True)
    await refresh_leaderboard()

@bot.slash_command(name="del", description="Supprime un joueur")
async def delete(inter, riot_id: str):
    if not inter.author.guild_permissions.administrator: return
    name, tag = riot_id.split("#")
    players_col.delete_one({"name": name, "tag": tag})
    await inter.response.send_message(f"🗑️ {riot_id} supprimé.", ephemeral=True)
    await refresh_leaderboard()

bot.run(DISCORD_TOKEN)
