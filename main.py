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

# Système de points UNIFIÉ LoL / Valorant
# Chaque palier vaut 1000 pts, divisions +250/+500/+750
# Équivalences : Iron=Iron, Bronze=Bronze, Silver=Silver, Gold=Gold,
#   Platinum=Platinum, Emerald=Diamond, Diamond=Ascendant,
#   Master=Immortal, Grandmaster/Challenger=Radiant

UNIFIED_TIER_PTS = {
    # LoL
    "Iron":        0,
    "Bronze":      1000,
    "Silver":      2000,
    "Gold":        3000,
    "Platinum":    4000,
    "Emerald":     5000,
    "Diamond":     6000,
    "Master":      7000,
    "Grandmaster": 7500,
    "Challenger":  8000,
    # Valorant (mappé sur l'échelle LoL)
    # Iron=Iron, Bronze=Bronze, Silver=Silver, Gold=Gold, Platinum=Platinum
    # Diamond=Emerald, Ascendant=Diamond, Immortal=Master, Radiant=Grandmaster
    "Ascendant":   6000,
    "Immortal":    7000,
    "Radiant":     7500,
}

LOL_TIERS = [
    "Iron", "Bronze", "Silver", "Gold",
    "Platinum", "Emerald", "Diamond",
    "Master", "Grandmaster", "Challenger"
]
VALO_TIERS = [
    "Iron", "Bronze", "Silver", "Gold", "Platinum",
    "Diamond", "Ascendant", "Immortal", "Radiant"
]
DIVISION_BONUS = {"I": 750, "II": 500, "III": 250, "IV": 0}

QUEUE_LABELS = {
    "RANKED_SOLO_5x5":  "Solo/Duo",
    "RANKED_FLEX_SR":   "Flex",
    "RANKED_TFT":       "TFT",
    "RANKED_TFT_TURBO": "TFT Turbo",
    "RANKED_TFT_PAIRS": "TFT Duo",
}

LOL_EMOJIS = {
    "Iron":        "<:lol_iron:1498973388155125850>", 
    "Bronze":      "<:lol_bronze:1498973454454624427>",
    "Silver":      "<:lol_silver:1498973522347692053>", 
    "Gold":        "<:lol_gold:1498973566345940992>",
    "Platinum":    "<:lol_platinum:1498978094776717312>",
    "Emerald":     "<:lol_emerald:1498973675972591739>",
    "Diamond":     "<:lol_diamond:1498973713486315641>",
    "Master":      "<:lol_master:1498973764455759903>",
    "Grandmaster": "<:lol_grandmaster:1498973821024342036>",
    "Challenger":  "<:lol_challenger:1498973859808935978>",
    "Unranked":    "<:unranked:1498977045928214570> ",
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

def unified_pts(tier: str, division: str, lp_or_rr: int) -> int:
    """Calcule les points sur une échelle commune LoL/Valorant."""
    base = UNIFIED_TIER_PTS.get(tier, 0)
    if tier in ("Master", "Grandmaster", "Challenger", "Immortal", "Radiant"):
        return base + lp_or_rr
    # LP/RR s'ajoutent directement (0-100 normalement, parfois +100 en promo)
    return base + DIVISION_BONUS.get(division, 0) + lp_or_rr

# Alias pour compatibilité
def lol_pts(tier: str, division: str, lp: int) -> int:
    return unified_pts(tier, division, lp)

def valo_pts(tier: str, division: str, rr: int) -> int:
    return unified_pts(tier, division, rr)

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
    Utilise /by-puuid/ directement (accessible avec clé Dev).
    """
    default = {"pts": 0, "display": "Unranked", "emoji": LOL_EMOJIS["Unranked"]}

    puuid = get_puuid(name, tag)
    if not puuid:
        return default

    # endpoint /by-puuid accessible avec clé Dev (contrairement à /by-summoner)
    try:
        r = requests.get(
            f"https://euw1.api.riotgames.com/lol/league/v4/entries/by-puuid/{puuid}"
            f"?api_key={RIOT_TOKEN}",
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
    "global": "🏆  Classement Général — Top 10",
    "lol":    "<:lol_logo:1209157366809886811>   League of Legends — Meilleur Rang",
    "valo":   "<:valo_logo:1209157284035428362>   Valorant — Classement",
}

FOOTER = "🔄 Actualisé toutes les heures  •  dev by htf."
# Séparateurs invisibles pour élargir les colonnes
PAD = "   "   # espace demi-cadratin ×3


def build_embed(sorted_data: list, mode: str) -> disnake.Embed:
    embed = disnake.Embed(title=TITLES[mode], color=COLORS[mode])
    embed.set_footer(text=FOOTER)

    col_players = ""
    col_lol     = ""
    col_valo    = ""

    for i, p in enumerate(sorted_data[:10]):
        prefix = MEDALS[i] if i < 3 else f"**{i+1}.**"
        col_players += prefix + " " + p['name'] + "\n"
        col_lol     += p['l_emoji'] + "  " + p['l_display'] + PAD + "\n"
        col_valo    += p['v_emoji'] + "  " + p['v_display'] + PAD + "\n" 

    SPACER = "​"

    if mode == "global":
        embed.add_field(name=f"Joueurs{PAD}",          value=col_players or "—", inline=True)
        embed.add_field(name=f"<:lol_logo:1209157366809886811>  LoL{PAD}", value=col_lol    or "—", inline=True)
        embed.add_field(name="<:valo_logo:1209157284035428362>  Valorant",   value=col_valo    or "—", inline=True)
    elif mode == "lol":
        embed.add_field(name=f"Joueurs{PAD}",          value=col_players or "—", inline=True)
        embed.add_field(name=SPACER,                   value=SPACER,              inline=True)
        embed.add_field(name="<:lol_logo:1209157366809886811>  Rang LoL", value=col_lol     or "—", inline=True)
    else:
        embed.add_field(name=f"Joueurs{PAD}",          value=col_players or "—", inline=True)
        embed.add_field(name=SPACER,                   value=SPACER,              inline=True)
        embed.add_field(name="<:valo_logo:1209157284035428362>  Rang Valorant", value=col_valo or "—", inline=True)

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

    @disnake.ui.button(label="Valorant", emoji="<:valo_logo:1209157284035428362>", style=disnake.ButtonStyle.danger)
    async def btn_valo(self, button, inter):
        data = sorted(self.all_data, key=lambda x: x["v_pts"], reverse=True)
        await inter.response.edit_message(embed=build_embed(data, "valo"))

    @disnake.ui.button(label="League of Legends", emoji="<:lol_logo:1209157366809886811>", style=disnake.ButtonStyle.primary)
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
        await asyncio.sleep(1)   # évite le rate limit Henrik (429)
        l = get_lol_data(name, tag)
        await asyncio.sleep(0.5) # évite le rate limit Riot
        all_data.append({
            "name":      name,
            "v_display": v["display"], "v_pts": v["pts"], "v_emoji": v["emoji"],
            "l_display": l["display"], "l_pts": l["pts"], "l_emoji": l["emoji"],
            "total_pts": v["pts"] + l["pts"],
        })

    # Recalcul du total pour s'assurer que le tri est correct
    for p in all_data:
        p["total_pts"] = p["v_pts"] + p["l_pts"]

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

def check_riot_key():
    """Teste la clé Riot au démarrage et affiche un diagnostic clair."""
    r = requests.get(
        f"https://europe.api.riotgames.com/riot/account/v1/accounts/by-riot-id/test/test?api_key={RIOT_TOKEN}",
        timeout=8
    )
    if r.status_code == 403:
        print("❌ RIOT_TOKEN → 403 Forbidden : clé expirée ou invalide. Renouvelle-la sur https://developer.riotgames.com")
    elif r.status_code == 401:
        print("❌ RIOT_TOKEN → 401 Unauthorized : clé manquante ou mal copiée dans Railway.")
    elif r.status_code in (200, 404):
        # 404 = joueur 'test' introuvable mais la clé est valide
        print("✅ RIOT_TOKEN valide.")
    else:
        print(f"⚠️  RIOT_TOKEN → HTTP {r.status_code}: {r.text[:150]}")

@bot.event
async def on_ready():
    print(f"✅ Bot connecté : {bot.user}")
    if not HENRIK_TOKEN:
        print("⚠️  HENRIK_TOKEN manquant → Valorant sera Unranked !")
    check_riot_key()

    await refresh_leaderboard()
    auto_refresh.start()


import asyncio

def is_admin(inter: disnake.ApplicationCommandInteraction) -> bool:
    return inter.author.guild_permissions.administrator

def is_right_channel(inter: disnake.ApplicationCommandInteraction) -> bool:
    return inter.channel_id == CHANNEL_ID

async def send_temp(inter: disnake.ApplicationCommandInteraction, msg: str, delete_after: int = 5):
    """Répond en éphémère ET supprime la commande de l'utilisateur après delete_after secondes."""
    await inter.response.send_message(msg, ephemeral=True)
    # Tenter de supprimer le message original de la commande slash (pas toujours possible)
    try:
        await asyncio.sleep(delete_after)
        await inter.delete_original_response()
    except Exception:
        pass


@bot.slash_command(name="add", description="Ajouter un joueur au classement (admin)")
async def add(inter: disnake.ApplicationCommandInteraction, riot_id: str):
    # Vérif channel
    if not is_right_channel(inter):
        return await inter.response.send_message(
            f"❌ Cette commande n'est utilisable que dans <#{CHANNEL_ID}>.", ephemeral=True
        )
    # Vérif admin
    if not is_admin(inter):
        return await send_temp(inter, "❌ Réservé aux administrateurs.")
    # Vérif format
    if "#" not in riot_id:
        return await send_temp(inter, "❌ Format invalide. Utilise `Pseudo#TAG`.")

    name, tag = riot_id.split("#", 1)

    # Vérif que le Riot ID existe vraiment
    await inter.response.defer(ephemeral=True)
    puuid = get_puuid(name, tag)
    if not puuid:
        return await inter.edit_original_response(
            content=f"❌ Riot ID **{name}#{tag}** introuvable. Vérifie le pseudo et le tag."
        )

    players_col.update_one(
        {"name": name, "tag": tag},
        {"$set": {"name": name, "tag": tag}},
        upsert=True
    )
    await inter.edit_original_response(content=f"✅ **{name}#{tag}** ajouté au classement !")
    await asyncio.sleep(5)
    try:
        await inter.delete_original_response()
    except Exception:
        pass
    await refresh_leaderboard()


@bot.slash_command(name="remove", description="Retirer un joueur du classement (admin)")
async def remove(inter: disnake.ApplicationCommandInteraction, riot_id: str):
    if not is_right_channel(inter):
        return await inter.response.send_message(
            f"❌ Cette commande n'est utilisable que dans <#{CHANNEL_ID}>.", ephemeral=True
        )
    if not is_admin(inter):
        return await send_temp(inter, "❌ Réservé aux administrateurs.")
    if "#" not in riot_id:
        return await send_temp(inter, "❌ Format invalide. Utilise `Pseudo#TAG`.")

    name, tag = riot_id.split("#", 1)
    res = players_col.delete_one({"name": name, "tag": tag})

    if res.deleted_count:
        await send_temp(inter, f"🗑️ **{name}#{tag}** retiré du classement.")
        await refresh_leaderboard()
    else:
        await send_temp(inter, f"❓ **{name}#{tag}** n'est pas dans le classement.")


@bot.slash_command(name="refresh", description="Forcer la mise à jour du classement (admin)")
async def manual_refresh(inter: disnake.ApplicationCommandInteraction):
    if not is_right_channel(inter):
        return await inter.response.send_message(
            f"❌ Cette commande n'est utilisable que dans <#{CHANNEL_ID}>.", ephemeral=True
        )
    if not is_admin(inter):
        return await send_temp(inter, "❌ Réservé aux administrateurs.")
    await send_temp(inter, "🔄 Mise à jour en cours...", delete_after=3)
    await refresh_leaderboard()


bot.run(DISCORD_TOKEN)
