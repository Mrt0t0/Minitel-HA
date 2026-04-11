# Minitel-HA — 3615 MAISON

**Language / Langue:** [🇫🇷 Français](#minitel-ha--3615-maison) | [🇬🇧 English](#english)

**Contrôlez Home Assistant depuis un vrai Minitel (ou un navigateur web) en Vidéotex.**
**Control Home Assistant from a real Minitel terminal (or a web browser) using Videotex.**

[![Version](https://img.shields.io/badge/version-1.0-green)](https://github.com/XReyRobert/minitel-ha)
[![Python](https://img.shields.io/badge/python-3.12-blue)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/docker-ready-blue)](https://www.docker.com/)
[![License](https://img.shields.io/badge/license-MIT-yellow)](LICENSE)

---

## Description

Minitel-HA est une passerelle entre un **Minitel physique** (via ESP32/TelnetPro Iodeo ou Minimit) et **Home Assistant**. Il expose une interface Vidéotex complète accessible depuis :

- 🟢 **Un vrai Minitel** connecté via ESP32 (port WebSocket `:3615`)
- 🌐 **Un navigateur web** (émulateur HTML complet avec clavier virtuel port `:8080`)

Le serveur est écrit entièrement en Python natif (`aiohttp`, `websockets`, `pyyaml`) — aucune dépendance externe lourde. Le rendu HTML utilise Canvas API nativement — aucun framework JavaScript.

Fonctionne largement sur une petite machine type RaspberryPi.

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
│  Docker Container (python:3.12-slim + git)              │
│                                                         │
│  server.py ──── ws_minitel.py ─── ws://0.0.0.0:3615   │◄── Minitel + ESP32
│       │    └─── ws_browser.py ─── http://0.0.0.0:8080 │◄── Navigateur
│       │                                                 │
│  ha_client.py ──────────────────────────────────────── │──► HA :8123 REST
│  pagevideo.py  (rendu Vidéotex binaire)                 │
│  utils.py      (logger centralisé)                      │
│                                                         │
│  static/archives/*.vdt  (pages Vidéotex locales)        │
│  static/index.html      (émulateur Canvas HTML)         │
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

## 🚀 Déploiement Docker (recommandé)

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
Configurer avec un ESP32 pour se connecter en WebSocket à `ws:[IP_SERVEUR]:3615`

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
  token: eyJ...  # Home assistant // Long-Lived Access Token HA

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
    - id: "home_assistant"
      name: "Assistant HA"
    # - id: "conversation.groq"
    #   name: "Groq"

meteo:
  weather_entity: "weather.forecast_maison" #a adapter avec vos entités HA
```

### Découverte automatique des entités
```bash
docker compose run --rm minitel-ha python discover.py
```
Le merge est non-destructif : vos personnalisations (`name`, `area`, `visible`) sont conservées.

---

## 🔌 Connexion Minitel physique

### Via ESP32 (TelnetPro Iodeo ou Minimit)
```Configurer l'ESP32 pour se connecter en WebSocket à `ws:[IP_SERVEUR]:3615`
```
Louis H - https://iodeo.fr/ et https://www.multiplie.fr/produit/minimit/
---

## Pages Vidéotex (.vdt)

Les fichiers `.vdt` (Vidéotex binaire) peuvent être placés dans `static/archives/` et consultés depuis le mode `[R]` Archives.

**Sources de pages .vdt :** (Merci XReyRobert pour le travail)
- Dépôt : [github.com/XReyRobert/VideotexPagesRepository]
(https://github.com/XReyRobert/VideotexPagesRepository)
- Copier manuellement dans `static/archives/`

---

**Dépendances Python :** `aiohttp` `websockets` `pyyaml`

---
---

# English

# Minitel-HA — 3615 MAISON

**Control Home Assistant from a real Minitel terminal (or a web browser) using Videotex.**

[![Version](https://img.shields.io/badge/version-1.0-green)](https://github.com/XReyRobert/minitel-ha)
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
│  Docker Container (python:3.12-slim + git)             │
│                                                         │
│  server.py ──── ws_minitel.py ─── ws://0.0.0.0:3615    │◄── Minitel + ESP32
│       │    └─── ws_browser.py ─── http://0.0.0.0:8080  │◄── Browser
│       │                                                 │
│  ha_client.py ───────────────────────────────────────── │──► HA :8123 REST
│  pagevideo.py  (binary Videotex rendering)             │
│  utils.py      (central logger)                        │
│                                                         │
│  static/archives/*.vdt  (local Videotex pages)         │
│  static/index.html      (HTML Canvas emulator)         │
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

## Docker deployment

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
    - id: "home_assistant"
      name: "Assistant HA"

meteo:
  weather_entity: "weather.forecast_maison"
```

### Entity auto-discovery

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

Binary Videotex files (`.vdt`) can be placed in `static/archives/` and viewed from the `[R]` Archives mode.

**Sources for `.vdt` pages:**
- Repository: https://github.com/XReyRobert/VideotexPagesRepository
- Copy files manually into `static/archives/`

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
