# 🏆 Rank Tracker — Discord Bot

> **Bot Discord** qui suit et compare les performances des joueurs sur **League of Legends** et **Valorant** en temps réel, avec un classement automatisé basé sur un système de points cumulés.

---

## 🚀 Fonctionnalités

- 🥇 **Classement Dynamique** — Affiche un Top 10 des joueurs avec leurs rangs LoL et Valorant
- ⚖️ **Système de Points Unifié** — Chaque rang est converti en points sur une échelle commune aux deux jeux (ex: Ascendant Valorant = Diamond LoL)
- 🔄 **Mise à Jour Automatique** — Le classement se rafraîchit toutes les heures automatiquement
- 🎮 **Multi-Jeux** — Intègre les données de **LoL** (LP, division, Solo/Duo & Flex & TFT) et **Valorant** (RR, rang)
- 🔍 **Vérification des Riot ID** — Le bot vérifie que le Riot ID existe avant de l'ajouter
- 🔒 **Accès Restreint** — Commandes réservées aux administrateurs, utilisables uniquement dans le bon channel

---

## 📸 Aperçu

| Global | Valorant | LoL |
|--------|----------|-----|
| 🌍 Classement cumulé | 🔺 Tri par rang Valorant | ⚔️ Tri par meilleur rang LoL |

---

## ⚙️ Commandes

| Commande | Description |
|----------|-------------|
| `/add Pseudo#TAG` | Ajoute un joueur au classement |
| `/remove Pseudo#TAG` | Retire un joueur du classement |
| `/refresh` | Force la mise à jour immédiate |

---

## 🛠️ Détails Techniques

| Élément | Détail |
|--------|--------|
| **Langage** | Python |
| **Librairie Discord** | `disnake` |
| **Base de données** | MongoDB |
| **Hébergement** | Railway |
| **API LoL** | Riot Games API (`/lol/league/v4/entries/by-puuid`) |
| **API Valorant** | Henrik Dev API (v3 + fallback v1) |
| **Actualisation** | Toutes les 60 minutes |

---

## 📦 Installation

### 1. Cloner le dépôt

```bash
git clone https://github.com/tonpseudo/rank-tracker-bot.git
cd rank-tracker-bot
```

### 2. Installer les dépendances

```bash
pip install disnake pymongo requests
```

### 3. Configurer les variables d'environnement

```env
DISCORD_TOKEN=ton_token_discord
RIOT_TOKEN=RGAPI-xxxx-xxxx        # Renouveler toutes les 24h sur developer.riotgames.com
HENRIK_TOKEN=HDEV-xxxx-xxxx       # Gratuit sur discord.gg/henrikdev
MONGO_URL=mongodb+srv://...
CHANNEL_ID=123456789012345678
```

### 4. Lancer le bot

```bash
python main.py
```

---

## 🧮 Système de Points

Le classement global est calculé sur une **échelle unifiée** qui rend les rangs des deux jeux comparables :

| LoL | Valorant équivalent | Points de base |
|-----|---------------------|----------------|
| Iron | Iron | 0 |
| Bronze | Bronze | 1 000 |
| Silver | Silver | 2 000 |
| Gold | Gold | 3 000 |
| Platinum | Platinum | 4 000 |
| Emerald | Diamond | 5 000 |
| Diamond | Ascendant | 6 000 |
| Master | Immortal | 7 000 |
| Grandmaster | Radiant | 7 500 |
| Challenger | — | 8 000 |

> Les **LP / RR** et les **divisions** s'ajoutent aux points de base.
> Sur LoL : **I > II > III > IV** — Sur Valorant : **3 > 2 > 1**

---

## 📄 Licence

MIT — Libre d'utilisation et de modification.

---

<p align="center">Développé par <strong>htf.</strong> 🎮</p>
