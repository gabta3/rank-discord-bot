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

# --- MAPPING EMOJIS ET POINTS ---
# Tu peux remplacer les emojis par des IDs d'emojis personnalisés de ton serveur si tu veux
RANK_EMOJIS = {
    "Iron": "🔘", "Bronze": "🟫", "Silver": "⬜", "Gold": "🟨", 
    "Platinum": "🔷", "Emerald": "💚", "Diamond": "💎", 
    "Master": "🔮", "Grandmaster": "🔴", "Challenger": "👑", "Unranked": "🌑"
}

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
            return RANK_EMOJIS[tier], pts
    return "🌑", 0

# --- RÉCUPÉRATION DONNÉES ---

def get_valo_data(name, tag):
    try:
        r = requests.get(f"https://api.henrikdev.xyz/valorant/v1/mmr/eu/{name}/{tag}", timeout=5).json()
        rank = r['data']['currenttierpatched']
        emoji, pts = get_rank_info(rank)
        return {"rank": rank, "emoji": emoji, "pts": pts}
    except: return {"rank": "Unranked", "emoji": "🌑", "pts": 0}

def get_lol_data(name, tag):
    try:
        acc = requests.get(f"https://europe.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{name}/{tag}?api_key={RIOT_TOKEN}", timeout=5).json()
        sum_data = requests.get(f"https://euw1.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{acc['puuid']}?api_key={RIOT_TOKEN}", timeout=5).json()
        leagues = requests.get(f"https://euw1.api.riotgames.com/lol/league/v4/entries/by-summoner/{sum_data['id']}?api_key={RIOT_TOKEN}", timeout=5).json()
        for l in leagues:
            if l['queueType'] == 'RANKED_SOLO_5x5':
                rank = f"{l['tier'].capitalize()} {l['rank']}"
                emoji, pts = get_rank_info(rank)
                return {"rank": rank, "emoji": emoji, "pts": pts}
    except: pass
    return {"rank": "Unranked", "emoji": "🌑", "pts": 0}

# --- INTERFACE ---

class LeaderboardView(disnake.ui.View):
    def __init__(self, data):
        super().__init__(timeout=None)
        self.data = data

    def create_embed(self, sorted_data, title, game_focus):
        embed = disnake.Embed(title=title, color=0xFFAA00)
        
        col_players = ""
        col_ranks = ""
        
        for i, p in enumerate(sorted_data[:15]): # Top 15
            medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else f"{i+1}."
            col_players += f"{medal} {p['name']}\n"
            
            # On affiche le rang du jeu sélectionné ou les deux
            if game_focus == "valo":
                col_ranks += f"{p['v_emoji']} {p['v_rank']}\n"
            elif game_focus == "lol":
                col_ranks += f"{p['l_emoji']} {p['l_rank']}\n"
            else:
                col_ranks += f"{p['v_emoji']} | {p['l_emoji']}\n"

        embed.add_field(name="Players", value=col_players, inline=True)
        embed.add_field(name="Rank", value=col_ranks, inline=True)
        embed.set_footer(text="Refreshed every hour • Use buttons to filter")
        return embed

    @disnake.ui.button(label="Global", emoji="🌍", style=disnake.ButtonStyle.secondary)
    async def sort_global(self, button, inter):
        sorted_data = sorted(self.data, key=lambda x: x['total_pts'], reverse=True)
        await inter.response.edit_message(embed=self.create_embed(sorted_data, "All Rank Leaderboard", "both"))

    @disnake.ui.button(label="Valorant", emoji="🔫", style=disnake.ButtonStyle.danger)
    async def sort_valo(self, button, inter):
        sorted_data = sorted(self.data, key=lambda x: x['v_pts'], reverse=True)
        await inter.response.edit_message(embed=self.create_embed(sorted_data, "Valorant Leaderboard", "valo"))

    @disnake.ui.button(label="LoL", emoji="⚔️", style=disnake.ButtonStyle.primary)
    async def sort_lol(self, button, inter):
        sorted_data = sorted(self.data, key=lambda x: x['l_pts'], reverse=True)
        await inter.response.edit_message(embed=self.create_embed(sorted_data, "League Leaderboard", "lol"))

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
            "name": p['name'], "v_rank": v['rank'], "v_emoji": v['emoji'], "v_pts": v['pts'],
            "l_rank": l['rank'], "l_emoji": l['emoji'], "l_pts": l['pts'],
            "total_pts": v['pts'] + l['pts']
        })

    if all_data:
        all_data.sort(key=lambda x: x['total_pts'], reverse=True)
        view = LeaderboardView(all_data)
        await channel.send(embed=view.create_embed(all_data, "All Rank Leaderboard", "both"), view=view)

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
