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

# ─────────────────────────────────────────
# RANK SYSTEM
# ─────────────────────────────────────────

TIER_ORDER = [
    "Iron", "Bronze", "Silver", "Gold",
    "Platinum", "Emerald", "Diamond",
    "Master", "Grandmaster", "Challenger"
]

DIVISION_BONUS = {"I": 300, "II": 200, "III": 100, "IV": 0}

VALO_TIER_ORDER = [
    "Iron", "Bronze", "Silver", "Gold", "Platinum",
    "Diamond", "Ascendant", "Immortal", "Radiant"
]

TIER_EMOJIS_LOL = {
    "Iron": "🩶", "Bronze": "🤎", "Silver": "🩵",
    "Gold": "🏅", "Platinum": "💠", "Emerald": "💚",
    "Diamond": "💎", "Master": "👑", "Grandmaster": "🔱", "Challenger": "⚡"
}

TIER_EMOJIS_VALO = {
    "Iron": "⬛", "Bronze": "🟤", "Silver": "⬜",
    "Gold": "🟡", "Platinum": "🔷", "Diamond": "💎",
    "Ascendant": "🌿", "Immortal": "🔴", "Radiant": "✨"
}

def lol_rank_to_pts(tier: str, division: str, lp: int) -> int:
    base = TIER_ORDER.index(tier) * 400 if tier in TIER_ORDER else 0
    div_bonus = DIVISION_BONUS.get(division, 0)
    return base + div_bonus + lp

def valo_rank_to_pts(tier: str, division: str, rr: int) -> int:
    base = VALO_TIER_ORDER.index(tier) * 400 if tier in VALO_TIER_ORDER else 0
    div_bonus = DIVISION_BONUS.get(division, 0)
    return base + div_bonus + rr

# ─────────────────────────────────────────
# API CALLS
# ─────────────────────────────────────────

def get_puuid(name: str, tag: str, region: str = "europe") -> str | None:
    """Récupère le PUUID via l'API Riot Account v1."""
    url = (
        f"https://{region}.api.riotgames.com/riot/account/v1/accounts"
        f"/by-riot-id/{name}/{tag}?api_key={RIOT_TOKEN}"
    )
    try:
        r = requests.get(url, timeout=8)
        if r.status_code == 200:
            return r.json().get("puuid")
        print(f"[PUUID] {name}#{tag} → HTTP {r.status_code}: {r.text[:120]}")
    except Exception as e:
        print(f"[PUUID] Exception pour {name}#{tag}: {e}")
    return None


def get_lol_data(name: str, tag: str) -> dict:
    """
    Retourne les données LoL ranked Solo/Duo d'un joueur.
    Fallback sur Flex si pas de Solo/Duo.
    """
    default = {"rank": "Unranked", "pts": 0, "display": "Unranked", "emoji": "❓"}

    puuid = get_puuid(name, tag, region="europe")
    if not puuid:
        return default

    # Summoner par PUUID (EUW1)
    try:
        sum_url = (
            f"https://euw1.api.riotgames.com/lol/summoner/v4/summoners"
            f"/by-puuid/{puuid}?api_key={RIOT_TOKEN}"
        )
        r_sum = requests.get(sum_url, timeout=8)
        if r_sum.status_code != 200:
            print(f"[LoL Summoner] {name}#{tag} → HTTP {r_sum.status_code}: {r_sum.text[:120]}")
            return default
        summoner_id = r_sum.json().get("id")
    except Exception as e:
        print(f"[LoL Summoner] Exception {name}: {e}")
        return default

    # Entries ranked
    try:
        league_url = (
            f"https://euw1.api.riotgames.com/lol/league/v4/entries"
            f"/by-summoner/{summoner_id}?api_key={RIOT_TOKEN}"
        )
        leagues = requests.get(league_url, timeout=8).json()
    except Exception as e:
        print(f"[LoL League] Exception {name}: {e}")
        return default

    priority = {"RANKED_SOLO_5x5": 0, "RANKED_FLEX_SR": 1}
    best = None
    best_prio = 99

    for entry in leagues:
        q = entry.get("queueType", "")
        p = priority.get(q, 99)
        if p < best_prio:
            best = entry
            best_prio = p

    if not best:
        return default

    tier = best["tier"].capitalize()
    division = best["rank"]          # "I", "II", "III", "IV"
    lp = best.get("leaguePoints", 0)
    queue_label = "Solo/Duo" if best["queueType"] == "RANKED_SOLO_5x5" else "Flex"

    # Master+ n'ont pas de division
    if tier in ("Master", "Grandmaster", "Challenger"):
        display = f"{tier} {lp} LP ({queue_label})"
        pts = lol_rank_to_pts(tier, "I", lp)
    else:
        display = f"{tier} {division} {lp} LP ({queue_label})"
        pts = lol_rank_to_pts(tier, division, lp)

    emoji = TIER_EMOJIS_LOL.get(tier, "🎮")
    return {"rank": f"{tier} {division}", "pts": pts, "display": display, "emoji": emoji}


def get_valo_data(name: str, tag: str) -> dict:
    """
    Récupère le rang Valorant via l'API Riot VAL-RANKED v1.
    Nécessite une clé de production pour VAL ; avec une clé Dev,
    on tombe en 403 → on fallback sur HenrikDev (sans token).
    """
    default = {"rank": "Unranked", "pts": 0, "display": "Unranked", "emoji": "❓"}

    puuid = get_puuid(name, tag, region="europe")
    if not puuid:
        return default

    # Tentative API officielle Riot (VAL-RANKED-V1) — EUW
    try:
        url = (
            f"https://eu.api.riotgames.com/val/ranked/v1/leaderboards/by-act"
            # Note : endpoint simplifié, utilise plutôt MMR par PUUID si dispo
        )
        # L'API officielle Valorant ranked par PUUID n'est pas disponible en Dev key.
        # On part donc directement sur HenrikDev qui est fiable pour les clés Dev.
    except Exception:
        pass

    # Fallback HenrikDev (gratuit, pas de token requis)
    try:
        henrik_url = f"https://api.henrikdev.xyz/valorant/v1/by-puuid/mmr/eu/{puuid}"
        r = requests.get(henrik_url, timeout=8)
        if r.status_code == 200:
            data = r.json().get("data", {})
            if data:
                tier_name = data.get("currenttierpatched", "")   # ex: "Diamond 2"
                rr = data.get("ranking_in_tier", 0)              # RR dans le rang

                # Séparer tier et division
                parts = tier_name.split()
                if len(parts) >= 2:
                    tier = parts[0].capitalize()
                    division_map = {"1": "I", "2": "II", "3": "III", "4": "IV"}
                    division = division_map.get(parts[1], parts[1])
                else:
                    tier = tier_name.capitalize()
                    division = ""

                if tier in ("Radiant", "Immortal"):
                    display = f"{tier} {rr} RR"
                    pts = valo_rank_to_pts(tier, "I", rr)
                else:
                    display = f"{tier} {division} {rr} RR"
                    pts = valo_rank_to_pts(tier, division, rr)

                emoji = TIER_EMOJIS_VALO.get(tier, "🎯")
                return {"rank": tier, "pts": pts, "display": display, "emoji": emoji}
        print(f"[Valo Henrik] {name}#{tag} → HTTP {r.status_code}: {r.text[:120]}")
    except Exception as e:
        print(f"[Valo Henrik] Exception {name}: {e}")

    return default

# ─────────────────────────────────────────
# EMBED BUILDER
# ─────────────────────────────────────────

MEDALS = ["🥇", "🥈", "🥉"]


def build_embed(sorted_data: list, title: str, mode: str) -> disnake.Embed:
    """
    Construit l'embed leaderboard style image 1.
    mode : "global" | "lol" | "valo"
    """
    color_map = {"global": 0xFFAA00, "lol": 0x3B82F6, "valo": 0xEF4444}
    embed = disnake.Embed(title=title, color=color_map.get(mode, 0xFFAA00))
    embed.set_footer(text="🔄 Rafraîchi toutes les heures")

    col_players = ""
    col_ranks = ""

    for i, p in enumerate(sorted_data[:10]):
        prefix = MEDALS[i] if i < 3 else f"**{i + 1}.**"
        col_players += f"{prefix} {p['name']}\n"

        if mode == "global":
            col_ranks += (
                f"{p['v_emoji']} `{p['v_display']}` | "
                f"{p['l_emoji']} `{p['l_display']}`\n"
            )
        elif mode == "valo":
            col_ranks += f"{p['v_emoji']} `{p['v_display']}`\n"
        else:  # lol
            col_ranks += f"{p['l_emoji']} `{p['l_display']}`\n"

    embed.add_field(name="Joueurs", value=col_players or "—", inline=True)
    embed.add_field(name="Rang", value=col_ranks or "—", inline=True)
    return embed

# ─────────────────────────────────────────
# VIEW (BOUTONS)
# ─────────────────────────────────────────

class LeaderboardView(disnake.ui.View):
    def __init__(self, all_data: list):
        super().__init__(timeout=None)
        self.all_data = all_data

    @disnake.ui.button(label="Global", emoji="🌍", style=disnake.ButtonStyle.secondary)
    async def btn_global(self, button, inter):
        data = sorted(self.all_data, key=lambda x: x["total_pts"], reverse=True)
        await inter.response.edit_message(
            embed=build_embed(data, "🌍 Classement Global", "global")
        )

    @disnake.ui.button(label="Valorant", emoji="🔴", style=disnake.ButtonStyle.danger)
    async def btn_valo(self, button, inter):
        data = sorted(self.all_data, key=lambda x: x["v_pts"], reverse=True)
        await inter.response.edit_message(
            embed=build_embed(data, "🔴 Classement Valorant", "valo")
        )

    @disnake.ui.button(label="LoL", emoji="🔵", style=disnake.ButtonStyle.primary)
    async def btn_lol(self, button, inter):
        data = sorted(self.all_data, key=lambda x: x["l_pts"], reverse=True)
        await inter.response.edit_message(
            embed=build_embed(data, "🔵 Classement League of Legends", "lol")
        )

# ─────────────────────────────────────────
# REFRESH LOGIC
# ─────────────────────────────────────────

async def refresh_leaderboard():
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        print(f"[Refresh] Channel {CHANNEL_ID} introuvable.")
        return

    # Supprime les anciens messages du bot
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
            "name": name,
            "v_display": v["display"], "v_pts": v["pts"], "v_emoji": v["emoji"],
            "l_display": l["display"], "l_pts": l["pts"], "l_emoji": l["emoji"],
            "total_pts": v["pts"] + l["pts"],
        })

    all_data.sort(key=lambda x: x["total_pts"], reverse=True)
    view = LeaderboardView(all_data)
    embed = build_embed(all_data, "🌍 Classement Global", "global")
    await channel.send(embed=embed, view=view)

# ─────────────────────────────────────────
# TÂCHE AUTO (toutes les heures)
# ─────────────────────────────────────────

@tasks.loop(hours=1)
async def auto_refresh():
    await refresh_leaderboard()

@auto_refresh.before_loop
async def before_refresh():
    await bot.wait_until_ready()

# ─────────────────────────────────────────
# EVENTS & COMMANDES
# ─────────────────────────────────────────

@bot.event
async def on_ready():
    print(f"✅ Bot connecté : {bot.user}")
    await refresh_leaderboard()
    auto_refresh.start()


@bot.slash_command(name="add", description="Ajouter un joueur au leaderboard")
async def add(inter: disnake.ApplicationCommandInteraction, riot_id: str):
    """Ajoute un joueur. Format : Pseudo#TAG"""
    if not inter.author.guild_permissions.administrator:
        await inter.response.send_message(
            "❌ Réservé aux admins.", ephemeral=True
        )
        return

    if "#" not in riot_id:
        await inter.response.send_message(
            "❌ Format invalide. Utilise `Pseudo#TAG`.", ephemeral=True
        )
        return

    name, tag = riot_id.split("#", 1)
    players_col.update_one(
        {"name": name, "tag": tag},
        {"$set": {"name": name, "tag": tag}},
        upsert=True
    )
    await inter.response.send_message(
        f"✅ **{name}#{tag}** ajouté ! Mise à jour du leaderboard...", ephemeral=True
    )
    await refresh_leaderboard()


@bot.slash_command(name="remove", description="Retirer un joueur du leaderboard")
async def remove(inter: disnake.ApplicationCommandInteraction, riot_id: str):
    """Retire un joueur. Format : Pseudo#TAG"""
    if not inter.author.guild_permissions.administrator:
        await inter.response.send_message("❌ Réservé aux admins.", ephemeral=True)
        return

    if "#" not in riot_id:
        await inter.response.send_message(
            "❌ Format invalide. Utilise `Pseudo#TAG`.", ephemeral=True
        )
        return

    name, tag = riot_id.split("#", 1)
    result = players_col.delete_one({"name": name, "tag": tag})
    if result.deleted_count:
        await inter.response.send_message(
            f"🗑️ **{name}#{tag}** retiré.", ephemeral=True
        )
        await refresh_leaderboard()
    else:
        await inter.response.send_message(
            f"❓ **{name}#{tag}** introuvable en base.", ephemeral=True
        )


@bot.slash_command(name="refresh", description="Forcer la mise à jour du leaderboard")
async def manual_refresh(inter: disnake.ApplicationCommandInteraction):
    if not inter.author.guild_permissions.administrator:
        await inter.response.send_message("❌ Réservé aux admins.", ephemeral=True)
        return
    await inter.response.send_message("🔄 Mise à jour en cours...", ephemeral=True)
    await refresh_leaderboard()


bot.run(DISCORD_TOKEN)
