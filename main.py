import disnake
import os
import requests
from disnake.ext import commands, tasks
from pymongo import MongoClient

# ─────────────────────────────────────────
# CONFIGURATION  (variables d'environnement Railway)
# ─────────────────────────────────────────
MONGO_URL      = os.getenv("MONGO_URL")
RIOT_TOKEN     = os.getenv("RIOT_TOKEN")          # Clé Dev Riot (renouveler chaque 24h)
HENRIK_TOKEN   = os.getenv("HENRIK_TOKEN")        # Clé HenrikDev GRATUITE → https://discord.gg/henrikdev
DISCORD_TOKEN  = os.getenv("DISCORD_TOKEN")
CHANNEL_ID     = int(os.getenv("CHANNEL_ID", 0))

mongo_client = MongoClient(MONGO_URL)
db           = mongo_client["rank_bot"]
players_col  = db["players"]

bot = commands.InteractionBot()

# ─────────────────────────────────────────
# SYSTEME DE POINTS (pour tri)
# ─────────────────────────────────────────

LOL_TIERS = [
    "Iron", "Bronze", "Silver", "Gold",
    "Platinum", "Emerald", "Diamond",
    "Master", "Grandmaster", "Challenger"
]
VALO_TIERS = [
    "Iron", "Bronze", "Silver", "Gold", "Platinum",
    "Diamond", "Ascendant", "Immortal", "Radiant"
]
DIVISION_BONUS = {"I": 300, "II": 200, "III": 100, "IV": 0}

QUEUE_LABELS = {
    "RANKED_SOLO_5x5":  "Solo/Duo",
    "RANKED_FLEX_SR":   "Flex",
    "RANKED_TFT":       "TFT",
    "RANKED_TFT_TURBO": "TFT Turbo",
    "RANKED_TFT_PAIRS": "TFT Duo",
}

LOL_EMOJIS = {
    "Iron":        "⬛",
    "Bronze":      "🟫",
    "Silver":      "🩶",
    "Gold":        "🟡",
    "Platinum":    "🩵",
    "Emerald":     "🟢",
    "Diamond":     "🔹",
    "Master":      "🟣",
    "Grandmaster": "🔴",
    "Challenger":  "🔱",
    "Unranked":    "⬜",
}

VALO_EMOJIS = {
    "Iron":      "⬛",
    "Bronze":    "🟫",
    "Silver":    "🩶",
    "Gold":      "🟡",
    "Platinum":  "🟦",
    "Diamond":   "🔷",
    "Ascendant": "🟩",
    "Immortal":  "🟥",
    "Radiant":   "🌟",
    "Unranked":  "⬜",
}

def lol_pts(tier: str, division: str, lp: int) -> int:
    base = LOL_TIERS.index(tier) * 400 if tier in LOL_TIERS else 0
    return base + DIVISION_BONUS.get(division, 0) + lp

def valo_pts(tier: str, division: str, rr: int) -> int:
    base = VALO_TIERS.index(tier) * 400 if tier in VALO_TIERS else 0
    return base + DIVISION_BONUS.get(division, 0) + rr

# ─────────────────────────────────────────
# API RIOT
# ─────────────────────────────────────────

def get_puuid(name: str, tag: str) -> str | None:
    url = (
        f"https://europe.api.riotgames.com/riot/account/v1/accounts"
        f"/by-riot-id/{name}/{tag}?api_key={RIOT_TOKEN}"
    )
    try:
        r = requests.get(url, timeout=8)
        if r.status_code == 200:
            return r.json().get("puuid")
        print(f"[PUUID] {name}#{tag} → {r.status_code}: {r.text[:150]}")
    except Exception as e:
        print(f"[PUUID] Exception {name}#{tag}: {e}")
    return None


def get_lol_data(name: str, tag: str) -> dict:
    """
    Retourne le MEILLEUR rang LoL tous modes confondus (Solo/Duo, Flex, TFT…)
    trié par points. Affiche le mode : ex. 'Platinum IV 23 LP (TFT)'.
    """
    default = {"pts": 0, "display": "Unranked", "emoji": LOL_EMOJIS["Unranked"]}

    puuid = get_puuid(name, tag)
    if not puuid:
        return default

    try:
        r = requests.get(
            f"https://euw1.api.riotgames.com/lol/summoner/v4/summoners"
            f"/by-puuid/{puuid}?api_key={RIOT_TOKEN}",
            timeout=8
        )
        if r.status_code != 200:
            print(f"[LoL Summoner] {name}#{tag} → {r.status_code}: {r.text[:150]}")
            return default
        summoner_id = r.json().get("id")
    except Exception as e:
        print(f"[LoL Summoner] Exception {name}: {e}")
        return default

    try:
        r = requests.get(
            f"https://euw1.api.riotgames.com/lol/league/v4/entries"
            f"/by-summoner/{summoner_id}?api_key={RIOT_TOKEN}",
            timeout=8
        )
        leagues = r.json()
        if not isinstance(leagues, list):
            print(f"[LoL League] {name}#{tag} → {r.status_code}: {leagues}")
            return default
    except Exception as e:
        print(f"[LoL League] Exception {name}: {e}")
        return default

    best     = None
    best_pts = -1

    for entry in leagues:
        if not isinstance(entry, dict):
            continue
        t  = entry.get("tier", "").capitalize()
        d  = entry.get("rank", "IV")
        lp = entry.get("leaguePoints", 0)
        if t not in LOL_TIERS:
            continue
        p = lol_pts(t, d, lp)
        if p > best_pts:
            best_pts = p
            best = entry

    if not best:
        return default

    tier     = best["tier"].capitalize()
    division = best["rank"]
    lp       = best.get("leaguePoints", 0)
    q_label  = QUEUE_LABELS.get(best.get("queueType", ""), "?")

    if tier in ("Master", "Grandmaster", "Challenger"):
        display = f"{tier} {lp} LP ({q_label})"
    else:
        display = f"{tier} {division} {lp} LP ({q_label})"

    return {"pts": best_pts, "display": display, "emoji": LOL_EMOJIS.get(tier, "🎮")}


def get_valo_data(name: str, tag: str) -> dict:
    """
    Rang Valorant via HenrikDev API.
    Token gratuit : rejoindre https://discord.gg/henrikdev → #get-api-key
    Ajouter HENRIK_TOKEN dans les variables Railway.
    """
    default = {"pts": 0, "display": "Unranked", "emoji": VALO_EMOJIS["Unranked"]}

    headers = {}
    if HENRIK_TOKEN:
        headers["Authorization"] = HENRIK_TOKEN

    try:
        # Essai v3 d'abord
        r = requests.get(
            f"https://api.henrikdev.xyz/valorant/v3/mmr/eu/pc/{name}/{tag}",
            headers=headers, timeout=8
        )
        if r.status_code == 200:
            data    = r.json().get("data", {})
            current = data.get("current", {})
            tier_name = current.get("tier", {}).get("name", "")
            rr        = current.get("rr", 0)
        else:
            # Fallback v1
            r2 = requests.get(
                f"https://api.henrikdev.xyz/valorant/v1/mmr/eu/{name}/{tag}",
                headers=headers, timeout=8
            )
            if r2.status_code != 200:
                print(f"[Valo] {name}#{tag} → v3:{r.status_code} v1:{r2.status_code}: {r2.text[:150]}")
                return default
            d2        = r2.json().get("data", {})
            tier_name = d2.get("currenttierpatched", "")
            rr        = d2.get("ranking_in_tier", 0)

        parts    = tier_name.split()
        div_map  = {"1": "I", "2": "II", "3": "III", "4": "IV"}
        if len(parts) >= 2:
            tier     = parts[0].capitalize()
            division = div_map.get(parts[1], parts[1])
        else:
            tier     = tier_name.capitalize()
            division = ""

        if not tier or tier.lower() == "unranked":
            return default

        pts = valo_pts(tier, division, rr)
        if tier in ("Radiant", "Immortal"):
            display = f"{tier} {rr} RR"
        else:
            display = f"{tier} {division} {rr} RR"

        return {"pts": pts, "display": display, "emoji": VALO_EMOJIS.get(tier, "🎯")}

    except Exception as e:
        print(f"[Valo] Exception {name}#{tag}: {e}")
    return default

# ─────────────────────────────────────────
# EMBED BUILDER
# ─────────────────────────────────────────

MEDALS = ["🥇", "🥈", "🥉"]

COLORS = {"global": 0xF0A500, "lol": 0x1A78BF, "valo": 0xE8412A}

TITLES = {
    "global": "🏆  All Rank Leaderboard — Top 10",
    "lol":    "⚔️  League of Legends — Meilleur Rang",
    "valo":   "🔺  Valorant — Classement",
}


def build_embed(sorted_data: list, mode: str) -> disnake.Embed:
    embed = disnake.Embed(title=TITLES[mode], color=COLORS[mode])
    embed.set_footer(text="🔄 Refreshed every hour")

    col_players = ""
    col_ranks   = ""

    for i, p in enumerate(sorted_data[:10]):
        prefix = MEDALS[i] if i < 3 else f"**{i+1}.**"

        if mode == "global":
            # deux lignes par joueur : Valo puis LoL
            col_players += f"{prefix} {p['name']}\n\u200b\n"
            col_ranks   += (
                f"{p['v_emoji']} `{p['v_display']}`\n"
                f"{p['l_emoji']} `{p['l_display']}`\n"
            )
        elif mode == "valo":
            col_players += f"{prefix} {p['name']}\n"
            col_ranks   += f"{p['v_emoji']} `{p['v_display']}`\n"
        else:
            col_players += f"{prefix} {p['name']}\n"
            col_ranks   += f"{p['l_emoji']} `{p['l_display']}`\n"

    embed.add_field(name="Joueurs", value=col_players or "—", inline=True)
    embed.add_field(name="Rang",    value=col_ranks   or "—", inline=True)
    return embed

# ─────────────────────────────────────────
# VIEW — BOUTONS
# ─────────────────────────────────────────

class LeaderboardView(disnake.ui.View):
    def __init__(self, all_data: list):
        super().__init__(timeout=None)
        self.all_data = all_data

    @disnake.ui.button(label="Global", emoji="🌍", style=disnake.ButtonStyle.secondary)
    async def btn_global(self, button, inter):
        data = sorted(self.all_data, key=lambda x: x["total_pts"], reverse=True)
        await inter.response.edit_message(embed=build_embed(data, "global"))

    @disnake.ui.button(label="Valorant", emoji="🔺", style=disnake.ButtonStyle.danger)
    async def btn_valo(self, button, inter):
        data = sorted(self.all_data, key=lambda x: x["v_pts"], reverse=True)
        await inter.response.edit_message(embed=build_embed(data, "valo"))

    @disnake.ui.button(label="League of Legends", emoji="⚔️", style=disnake.ButtonStyle.primary)
    async def btn_lol(self, button, inter):
        data = sorted(self.all_data, key=lambda x: x["l_pts"], reverse=True)
        await inter.response.edit_message(embed=build_embed(data, "lol"))

# ─────────────────────────────────────────
# REFRESH
# ─────────────────────────────────────────

async def refresh_leaderboard():
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        print(f"[Refresh] Channel {CHANNEL_ID} introuvable.")
        return

    async for msg in channel.history(limit=10):
        if msg.author == bot.user:
            try:
                await msg.delete()
            except Exception:
                pass

    players = list(players_col.find())
    if not players:
        await channel.send("📭 Aucun joueur enregistré. Utilise `/add Pseudo#TAG`.")
        return

    all_data = []
    for p in players:
        name, tag = p["name"], p["tag"]
        v = get_valo_data(name, tag)
        l = get_lol_data(name, tag)
        all_data.append({
            "name":      name,
            "v_display": v["display"], "v_pts": v["pts"], "v_emoji": v["emoji"],
            "l_display": l["display"], "l_pts": l["pts"], "l_emoji": l["emoji"],
            "total_pts": v["pts"] + l["pts"],
        })

    all_data.sort(key=lambda x: x["total_pts"], reverse=True)
    view  = LeaderboardView(all_data)
    embed = build_embed(all_data, "global")
    await channel.send(embed=embed, view=view)

# ─────────────────────────────────────────
# AUTO-REFRESH
# ─────────────────────────────────────────

@tasks.loop(hours=1)
async def auto_refresh():
    await refresh_leaderboard()

@auto_refresh.before_loop
async def before_refresh():
    await bot.wait_until_ready()

# ─────────────────────────────────────────
# EVENTS & SLASH COMMANDS
# ─────────────────────────────────────────

@bot.event
async def on_ready():
    print(f"✅ Bot connecté : {bot.user}")
    if not HENRIK_TOKEN:
        print("⚠️  HENRIK_TOKEN manquant → Valorant sera Unranked !")
    await refresh_leaderboard()
    auto_refresh.start()


@bot.slash_command(name="add", description="Ajouter un joueur (admin)")
async def add(inter: disnake.ApplicationCommandInteraction, riot_id: str):
    if not inter.author.guild_permissions.administrator:
        return await inter.response.send_message("❌ Réservé aux admins.", ephemeral=True)
    if "#" not in riot_id:
        return await inter.response.send_message("❌ Format : `Pseudo#TAG`", ephemeral=True)
    name, tag = riot_id.split("#", 1)
    players_col.update_one({"name": name, "tag": tag}, {"$set": {"name": name, "tag": tag}}, upsert=True)
    await inter.response.send_message(f"✅ **{name}#{tag}** ajouté !", ephemeral=True)
    await refresh_leaderboard()


@bot.slash_command(name="remove", description="Retirer un joueur (admin)")
async def remove(inter: disnake.ApplicationCommandInteraction, riot_id: str):
    if not inter.author.guild_permissions.administrator:
        return await inter.response.send_message("❌ Réservé aux admins.", ephemeral=True)
    if "#" not in riot_id:
        return await inter.response.send_message("❌ Format : `Pseudo#TAG`", ephemeral=True)
    name, tag = riot_id.split("#", 1)
    res = players_col.delete_one({"name": name, "tag": tag})
    if res.deleted_count:
        await inter.response.send_message(f"🗑️ **{name}#{tag}** retiré.", ephemeral=True)
        await refresh_leaderboard()
    else:
        await inter.response.send_message(f"❓ **{name}#{tag}** introuvable.", ephemeral=True)


@bot.slash_command(name="refresh", description="Forcer la mise à jour (admin)")
async def manual_refresh(inter: disnake.ApplicationCommandInteraction):
    if not inter.author.guild_permissions.administrator:
        return await inter.response.send_message("❌ Réservé aux admins.", ephemeral=True)
    await inter.response.send_message("🔄 Mise à jour en cours...", ephemeral=True)
    await refresh_leaderboard()


bot.run(DISCORD_TOKEN)
