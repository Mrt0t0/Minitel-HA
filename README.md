# Minitel-HA — 3615 MAISON

**Language / Langue:** [🇫🇷 Français](#minitel-ha--3615-maison) | [🇬🇧 English](#english)

**Contrôlez Home Assistant depuis un vrai Minitel (ou un navigateur web) en Vidéotex.**

[![Version](https://img.shields.io/badge/version-1.1-green)](https://github.com/Mrt0t0/Minitel-HA)
[![Python](https://img.shields.io/badge/python-3.12-blue)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/docker-ready-blue)](https://www.docker.com/)
[![License](https://img.shields.io/badge/license-MIT-yellow)](LICENSE)

---

## Description

Minitel-HA est une passerelle entre un **Minitel physique** (via ESP32/TelnetPro Iodeo ou Minimit) et **Home Assistant**. Il expose une interface Vidéotex complète accessible depuis :

- 🟢 **Un vrai Minitel** connecté via ESP32 (port WebSocket `:3615`)
- 🌐 **Un navigateur web** (émulateur HTML complet avec clavier virtuel port `:8080`)

Le serveur est écrit entièrement en Python natif (`aiohttp`, `websockets`, `pyyaml`) — aucune dépendance externe lourde. Le rendu HTML utilise Canvas API nativement — aucun framework JavaScript.

Fonctionne largement sur une petite machine type Raspberry Pi.

---

## Nouveautés v1.1

| Domaine | Amélioration |
|---|---|
| **Installation** | Add-on Home Assistant officiel — installation en quelques clics, sans ligne de commande |
| **Performance** | Un seul appel `GET /api/states` au lieu d'un par entité (51 requêtes → 1) + cache 2 s |
| **API** | Routes `/api/archives/list` et `/api/archives/vdt/{nom}` (le lecteur .vdt du navigateur ne fonctionnait pas sans elles) |
| **Modes** | Assistant IA, Archives et Aide générale désormais disponibles côté navigateur *et* Minitel |
| **Vidéotex** | Séquences `ESC 0x58/0x59/0x5A/0x5C/0x5D/0x5F` conformes STUM1B, double hauteur ancrée en bas |
| **Robustesse** | Clés YAML vides tolérées, arrêt propre, fermeture des sessions et timers |
| **Sécurité** | Protection contre la traversée de répertoire sur `/api/archives/vdt/` |

---

## Fonctionnalités

### Modes disponibles
| Touche | Mode | Description |
|--------|------|-------------|
| `D` | **Domotique** | Contrôle ON/OFF des appareils par zone |
| `M` | **Météo** | Prévisions + températures/humidité par pièce |
| `S` | **Scènes** | Activation de scènes et scripts HA |
| `J` | **Journal** | Historique des 50 dernières actions |
| `A` | **Assistant** | IA conversationnelle Home Assistant (multi-agents) |
| `R` | **Archives** | Pages Vidéotex statiques (.vdt) avec auto-rotation |
| `H` | **Aide** | Guide d'utilisation intégré (7 pages) |

### Navigation
- `SOMMAIRE` → Menu principal depuis n'importe où
- `GUIDE` → Aide contextuelle du mode actif
- `SUITE` / `RETOUR` → Pagination
- `Lettre + ENVOI` → Changer de mode
- `1-9 + ENVOI` → Sélectionner/toggler un appareil

### Émulateur navigateur
- Splash screen animé 7 secondes
- Clavier Minitel virtuel
- Lecteur Vidéotex Canvas natif (G0 + G1 mosaïque + REP) (en Beta)
- Reconnexion WebSocket automatique

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  server.py ──── ws_minitel.py ─── ws://0.0.0.0:3615    │◄── Minitel + ESP32
│       │    └─── ws_browser.py ─── http://0.0.0.0:8080  │◄── Navigateur
│       │                                                  │
│  ha_client.py ───────────────────────────────────────── │──► HA :8123 REST
│  pagevideo.py  (rendu Vidéotex binaire)                  │
│  utils.py      (logger centralisé)                       │
│                                                          │
│  static/archives/*.vdt  (pages Vidéotex locales)         │
│  static/index.html      (émulateur Canvas HTML)          │
└─────────────────────────────────────────────────────────┘
```

**Fichiers du projet :**
```
minitel-ha/
├── server.py          # Orchestrateur principal
├── ha_client.py       # Client REST Home Assistant
├── pagevideo.py       # Rendu Vidéotex binaire
├── ws_minitel.py      # Handler WebSocket Minitel (:3615)
├── ws_browser.py      # Handler WebSocket navigateur (:8080)
├── utils.py           # Logger centralisé
├── pagehtml.py        # Injection port dans HTML
├── discover.py        # Découverte automatique entités HA
├── config.yaml        # Configuration principale
├── Dockerfile
├── docker-compose.yml
└── static/
    ├── index.html     # Émulateur navigateur
    └── archives/      # Pages .vdt (remplissage manuel)
```

---

## 🏠 Installation en add-on Home Assistant (recommandé)

La façon la plus simple d'installer Minitel-HA : tout se fait depuis l'interface Home Assistant, aucune ligne de commande.

### Prérequis
- Home Assistant OS ou Supervised (avec support des add-ons)
- Un token Long-Lived Access Token HA

### Installation

1. Dans Home Assistant : **Paramètres** → **Modules complémentaires** → **Boutique** → menu **⋮** → **Dépôts**
2. Ajouter : `https://github.com/Mrt0t0/Minitel-HA-addon`
3. Installer **Minitel-HA** depuis la liste des add-ons
4. Onglet **Configuration** : renseigner `ha_url` (ex. `http://homeassistant.local:8123`) et `ha_token`
5. Onglet **Info** → **Démarrer**
6. Accéder à l'émulateur : `http://[IP_HA]:8080`
7. Minitel physique (ESP32/TelnetPro/Minimit) : `ws://[IP_HA]:3615`

### Découverte automatique des entités

```bash
docker exec addon_minitel_ha python3 /app/discover.py
```

Puis **redémarrer l'add-on** pour que les nouveaux appareils apparaissent. Le merge est non-destructif : vos personnalisations (`name`, `area`, `visible`) sont conservées.

### Données persistantes

Le dossier `/share/minitel-ha/` survit aux mises à jour de l'add-on :
- `/share/minitel-ha/archives/` — déposez-y vos pages `.vdt`
- `/share/minitel-ha/config.yaml` — appareils et capteurs découverts

### Mise à jour
Depuis **Paramètres** → **Modules complémentaires** → **Minitel-HA** → **Mettre à jour** (si une nouvelle version est disponible dans le dépôt).

---

## 🐳 Installation Docker (avancé / hors Home Assistant)

Pour héberger Minitel-HA sur une machine séparée de Home Assistant (serveur dédié, NAS, Raspberry Pi indépendant).

### Prérequis
- Docker + Docker Compose
- Home Assistant accessible en réseau
- Un token Long-Lived Access Token HA

### Installation

```bash
# 1. Cloner le dépôt
git clone https://github.com/Mrt0t0/Minitel-HA
cd Minitel-HA

# 2. Configurer
nano config.yaml  # Renseigner URL HA, token, entités

# 3. Découverte automatique des entités HA (optionnel)
docker compose run --rm minitel-ha python discover.py

# 4. Lancer
docker compose build   # Première fois
docker compose up -d

# 5. Accéder à l'émulateur
open http://192.168.1.X:8080

# 6. Accéder avec un Minitel (via ESP32/TelnetPro Iodeo ou Minimit)
# Configurer l'ESP32 pour se connecter en WebSocket à ws://[IP_SERVEUR]:3615
```

### Mise à jour
```bash
cd Minitel-HA
git pull
docker compose up -d --build
```

### Logs
```bash
docker compose logs -f
```

---

## Configuration (`config.yaml`)

```yaml
homeassistant:
  url:   http://192.168.1.x:8123
  token: eyJ...  # Home Assistant // Long-Lived Access Token HA

server:
  vt_port:   3615   # WebSocket Minitel/ESP32
  http_port: 8080   # HTTP + WebSocket navigateur

display:
  splash_seconds: 7  # Durée splash screen

archives:
  folder:      "static/archives"
  auto_rotate: 30  # Rotation auto des .vdt (secondes)

assistant:
  language: "fr"
  agents:
    - id: "conversation.home_assistant"
      name: "Assistant HA"
    # - id: "conversation.groq"
    #   name: "Groq"

meteo:
  weather_entity: "weather.forecast_maison" # a adapter avec vos entités HA
```

### Découverte automatique des entités (installation Docker)
```bash
docker compose run --rm minitel-ha python discover.py
```
Le merge est non-destructif : vos personnalisations (`name`, `area`, `visible`) sont conservées.

---

## 🔌 Connexion Minitel physique

### Via ESP32 (TelnetPro Iodeo ou Minimit)
Configurer l'ESP32 pour se connecter en WebSocket à `ws://[IP_SERVEUR]:3615`

- Iodeo (Louis H) : https://iodeo.fr/
- Minimit : https://www.multiplie.fr/produit/minimit/

---

## Pages Vidéotex (.vdt)

Les fichiers `.vdt` (Vidéotex binaire) peuvent être placés dans `static/archives/` (Docker) ou `/share/minitel-ha/archives/` (add-on) et consultés depuis le mode `[R]` Archives.

**Sources de pages .vdt :** (Merci XReyRobert pour le travail)
- Dépôt : [github.com/XReyRobert/VideotexPagesRepository](https://github.com/XReyRobert/VideotexPagesRepository)
- Copier manuellement dans le dossier archives

---

## Limitations connues

- Le lecteur `.vdt` navigateur est en version bêta — les pages complexes peuvent présenter des imperfections de rendu.
- Le rendu Minitel physique est plus fidèle à la norme Vidéotex.

---

**Dépendances Python :** `aiohttp` `websockets` `pyyaml`

---
---

# English

# Minitel-HA — 3615 MAISON

**Control Home Assistant from a real Minitel terminal (or a web browser) using Videotex.**

[![Version](https://img.shields.io/badge/version-1.1-green)](https://github.com/Mrt0t0/Minitel-HA)
[![Python](https://img.shields.io/badge/python-3.12-blue)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/docker-ready-blue)](https://www.docker.com/)
[![License](https://img.shields.io/badge/license-MIT-yellow)](LICENSE)

---

## Description

Minitel-HA is a bridge between a **physical Minitel terminal** (through ESP32 / TelnetPro Iodeo or Minimit) and **Home Assistant**. It provides a full Videotex-style interface available from:

- 🟢 **A real Minitel** connected through ESP32 (WebSocket port `:3615`)
- 🌐 **A web browser** using a complete HTML emulator with a virtual keyboard (port `:8080`)

The server is written in pure Python (`aiohttp`, `websockets`, `pyyaml`) with no heavy external dependency. The browser renderer uses the native Canvas API and no JavaScript framework.

It runs well on small hardware such as a Raspberry Pi.

---

## What's new in v1.1

| Area | Improvement |
|---|---|
| **Installation** | Official Home Assistant add-on — install in a few clicks, no command line needed |
| **Performance** | Single `GET /api/states` call instead of one per entity (51 requests → 1) + 2 s cache |
| **API** | `/api/archives/list` and `/api/archives/vdt/{name}` routes (the browser .vdt reader could not work without them) |
| **Modes** | AI Assistant, Archives and general Help now available in the browser *and* on the Minitel |
| **Videotex** | `ESC 0x58/0x59/0x5A/0x5C/0x5D/0x5F` sequences now match STUM1B, double-height anchored at the bottom |
| **Robustness** | Empty YAML keys tolerated, clean shutdown, sessions and timers closed |
| **Security** | Directory-traversal protection on `/api/archives/vdt/` |

---

## Features

### Available modes

| Key | Mode | Description |
|-----|------|-------------|
| `D` | **Home control** | ON/OFF control of devices by area |
| `M` | **Weather** | Forecast + room temperature/humidity |
| `S` | **Scenes** | Trigger Home Assistant scenes and scripts |
| `J` | **Logbook** | History of the last 50 actions |
| `A` | **Assistant** | Home Assistant conversational AI (multi-agent) |
| `R` | **Archives** | Static Videotex pages (`.vdt`) with auto-rotation |
| `H` | **Help** | Built-in usage guide (7 pages) |

### Navigation

- `SOMMAIRE` → Main menu from anywhere
- `GUIDE` → Context help for the active mode
- `SUITE` / `RETOUR` → Pagination
- `Letter + ENVOI` → Switch mode
- `1-9 + ENVOI` → Select / toggle a device

### Browser emulator

- 7-second animated splash screen
- Virtual Minitel keyboard
- Native Canvas Videotex renderer (G0 + G1 mosaic + REP) (Beta)
- Automatic WebSocket reconnection

---

## Architecture

```text
┌─────────────────────────────────────────────────────────┐
│  server.py ──── ws_minitel.py ─── ws://0.0.0.0:3615     │◄── Minitel + ESP32
│       │    └─── ws_browser.py ─── http://0.0.0.0:8080   │◄── Browser
│       │                                                  │
│  ha_client.py ───────────────────────────────────────── │──► HA :8123 REST
│  pagevideo.py  (binary Videotex rendering)               │
│  utils.py      (central logger)                          │
│                                                          │
│  static/archives/*.vdt  (local Videotex pages)           │
│  static/index.html      (HTML Canvas emulator)           │
└─────────────────────────────────────────────────────────┘
```

**Project files:**

```text
minitel-ha/
├── server.py
├── ha_client.py
├── pagevideo.py
├── ws_minitel.py
├── ws_browser.py
├── utils.py
├── pagehtml.py
├── discover.py
├── config.yaml
├── Dockerfile
├── docker-compose.yml
└── static/
    ├── index.html
    └── archives/
```

---

## 🏠 Home Assistant add-on installation (recommended)

The simplest way to install Minitel-HA: everything happens from the Home Assistant UI, no command line needed.

### Requirements
- Home Assistant OS or Supervised (with add-on support)
- A Home Assistant Long-Lived Access Token

### Installation

1. In Home Assistant: **Settings** → **Add-ons** → **Add-on store** → **⋮** → **Repositories**
2. Add: `https://github.com/Mrt0t0/Minitel-HA-addon`
3. Install **Minitel-HA** from the add-on list
4. **Configuration** tab: set `ha_url` (e.g. `http://homeassistant.local:8123`) and `ha_token`
5. **Info** tab → **Start**
6. Open the browser emulator: `http://[HA_IP]:8080`
7. Physical Minitel (ESP32/TelnetPro/Minimit): `ws://[HA_IP]:3615`

### Entity auto-discovery

```bash
docker exec addon_minitel_ha python3 /app/discover.py
```

Then **restart the add-on** for new devices to appear. The merge is non-destructive: your custom values (`name`, `area`, `visible`) are preserved.

### Persistent data

`/share/minitel-ha/` survives add-on updates:
- `/share/minitel-ha/archives/` — drop your `.vdt` pages here
- `/share/minitel-ha/config.yaml` — discovered devices and sensors

### Update
From **Settings** → **Add-ons** → **Minitel-HA** → **Update** (when a new version is available in the repository).

---

## 🐳 Docker installation (advanced / outside Home Assistant)

For hosting Minitel-HA on a machine separate from Home Assistant (dedicated server, NAS, standalone Raspberry Pi).

### Requirements

- Docker + Docker Compose
- A reachable Home Assistant instance
- A Home Assistant Long-Lived Access Token

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/Mrt0t0/Minitel-HA
cd Minitel-HA

# 2. Configure
nano config.yaml

# 3. Auto-discover Home Assistant entities (optional)
docker compose run --rm minitel-ha python discover.py

# 4. Start
docker compose build
docker compose up -d

# 5. Open the browser emulator
# Open in your browser:
http://192.168.1.X:8080

# 6. Connect a real Minitel (via ESP32 / TelnetPro Iodeo / Minimit)
# Configure the ESP32 to connect to:
ws://[SERVER_IP]:3615
```

### Update

```bash
cd Minitel-HA
git pull
docker compose up -d --build
```

### Logs

```bash
docker compose logs -f
```

---

## Configuration (`config.yaml`)

```yaml
homeassistant:
  url:   http://192.168.1.x:8123
  token: eyJ...

server:
  vt_port:   3615
  http_port: 8080

display:
  splash_seconds: 7

archives:
  folder: "static/archives"
  auto_rotate: 30

assistant:
  language: "fr"
  agents:
    - id: "conversation.home_assistant"
      name: "Assistant HA"

meteo:
  weather_entity: "weather.forecast_maison"
```

### Entity auto-discovery (Docker install)

```bash
docker compose run --rm minitel-ha python discover.py
```

The merge is non-destructive: your custom values such as `name`, `area`, and `visible` are preserved.

---

## Physical Minitel connection

### Via ESP32 (TelnetPro Iodeo or Minimit)

Configure the ESP32 to connect through WebSocket to:

```text
ws://[SERVER_IP]:3615
```

Useful links:
- Iodeo: https://iodeo.fr/
- Minimit: https://www.multiplie.fr/produit/minimit/

---

## Videotex pages (`.vdt`)

Binary Videotex files (`.vdt`) can be placed in `static/archives/` (Docker) or `/share/minitel-ha/archives/` (add-on) and viewed from the `[R]` Archives mode.

**Sources for `.vdt` pages:**
- Repository: https://github.com/XReyRobert/VideotexPagesRepository
- Copy files manually into the archives folder

---

## Known limitations

- The browser-side `.vdt` renderer is still under active work.
- Some complex Videotex pages may render imperfectly depending on attributes and layout.
- Physical Minitel output is currently more reliable than the browser emulator for strict Videotex fidelity.

---

**Python dependencies:** `aiohttp` `websockets` `pyyaml`

---

*Minitel-HA 3615 MAISON — Home Assistant automation through Minitel*

*Minitel-HA 3615 MAISON — Domotique Home Assistant par Minitel*
