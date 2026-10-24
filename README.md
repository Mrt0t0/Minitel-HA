# Minitel-HA — 3615 MAISON

**Language / Langue:** [🇫🇷 Français](#minitel-ha--3615-maison) | [🇬🇧 English](#english)

**Contrôlez Home Assistant depuis un vrai Minitel (ou un navigateur web) en Vidéotex.**

[![Version](https://img.shields.io/badge/version-1.3-green)](https://github.com/Mrt0t0/Minitel-HA)
[![CI](https://github.com/Mrt0t0/Minitel-HA/actions/workflows/ci.yml/badge.svg)](https://github.com/Mrt0t0/Minitel-HA/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.12-blue)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/docker-ready-blue)](https://www.docker.com/)
[![License](https://img.shields.io/badge/license-MIT-yellow)](LICENSE)

| Domotique | Graphique 24 h |
|---|---|
| ![Domotique](https://raw.githubusercontent.com/Mrt0t0/Minitel-HA/main/screen/v13-domotique.png) | ![Graphique](https://raw.githubusercontent.com/Mrt0t0/Minitel-HA/main/screen/v13-graphique.png) |

---

## Description

Minitel-HA est une passerelle entre un **Minitel physique** (via ESP32 / TelnetPro Iodeo ou Minimit) et **Home Assistant**. Le même service Vidéotex est accessible depuis :

- 🟢 **un vrai Minitel** connecté par ESP32 (WebSocket, port `:3615`) ;
- 🌐 **un navigateur web** : émulateur Minitel avec clavier virtuel (port `:8080`, ou barre latérale de HA avec l'add-on).

Le navigateur affiche exactement les mêmes pages que le Minitel : une seule logique, un seul rendu.
Serveur en Python (`aiohttp`, `websockets`, `pyyaml`), émulateur en JavaScript natif (Canvas). Tourne sans difficulté sur un Raspberry Pi.

---

## Nouveautés v1.3

| Domaine | Nouveauté |
|---|---|
| **Temps réel** | Abonnement au WebSocket de Home Assistant : un changement d'état s'affiche immédiatement, seules les lignes concernées sont réécrites (le Minitel est à 1200 bauds). Repli automatique sur l'interrogation périodique |
| **Sécurité** | Code d'accès facultatif (Minitel et navigateur), 3 essais par connexion, blocage de l'adresse IP après 5 échecs. Add-on : accès par la barre latérale de HA (ingress) sans code |
| **Navigateur** | Véritable émulateur Minitel : pages identiques au Minitel, ligne 0, accents, curseur, double taille. Clavier physique et clavier virtuel (mobile) |
| **Capteurs** | Nouveau mode `C` : valeurs par pièce, graphique 24 h en semi-graphique Vidéotex (`Chiffre + ENVOI`) |
| **Appareils** | Volets, thermostats, lecteurs multimédia, serrures, ventilateurs. `SUITE` / `RETOUR` règlent l'appareil choisi (luminosité, position, consigne, volume) |
| **Alertes** | Ligne 0 du Minitel : porte ouverte, seuil de température… (`alerts` dans la configuration) |
| **Confirmations** | « Tout éteindre » (`*`) et le déverrouillage d'une serrure demandent `ENVOI` pour confirmer |
| **Journal** | Conservé sur disque entre deux redémarrages |
| **Langue** | Écrans en français ou en anglais (`display.language`) |
| **Archives** | Dépôt de pages `.vdt` depuis le navigateur (bouton `.vdt ⇪`) |
| **Qualité** | Une seule logique Minitel / navigateur, 36 tests automatiques, lint et CI GitHub Actions, image Docker construite |

Historique complet : [CHANGELOG de l'add-on](https://github.com/Mrt0t0/Minitel-HA-addon/blob/main/minitel-ha/CHANGELOG.md).

---

## Fonctionnalités

### Modes

| Touche | Mode | Description |
|---|---|---|
| `D` | **Domotique** | Appareils par pièce : bascule, réglages, état en temps réel |
| `C` | **Capteurs** | Relevés par pièce et graphique 24 h |
| `M` | **Météo** | Prévisions + températures / humidité par pièce |
| `S` | **Scènes** | Scènes et scripts HA |
| `J` | **Journal** | Dernières actions (conservées sur disque) |
| `A` | **Assistant** | IA conversationnelle de Home Assistant (plusieurs agents) |
| `R` | **Archives** | Pages Vidéotex `.vdt`, rotation automatique |
| `H` | **Aide** | Guide intégré (8 pages) |

### Touches

| Touche Minitel | Clavier du navigateur | Effet |
|---|---|---|
| Lettre | Lettre | Change de mode (depuis le menu et tous les modes sauf l'assistant) |
| `SOMMAIRE` | `Échap` | Menu principal |
| `GUIDE` | `F1` | Aide du mode en cours, puis aide générale |
| `ENVOI` | `Entrée` | Valide (bascule, ouvre, envoie, confirme) |
| `SUITE` / `RETOUR` | `→` / `←` | Page suivante / précédente, ou réglage +/− de l'appareil choisi |
| `CORRECTION` | `Retour arrière` | Efface la saisie |
| `ANNULATION` | `Suppr` | Annule / revient à la liste |
| `REPETITION` | `F2` | Rafraîchit l'écran (assistant : nouvelle conversation) |

En mode **Domotique** : `1`–`9` choisit un appareil, `ENVOI` le bascule, `SUITE` / `RETOUR` le règlent, `*` éteint tout, `0` ouvre le journal.

---

## Architecture

```
            Minitel + ESP32 ──ws :3615──► ws_minitel.py ─┐
 Navigateur (émulateur Canvas) ─ws :8080/ws─► ws_browser.py ─┤
                                                             ▼
                          session.py  (une session par terminal : modes, touches)
                             │            │
                     pagevideo.py     devices.py   (états, actions, réglages par type)
                     (pages Vidéotex)     │
                             │       hub.py  ◄── ha_live.py ◄── WebSocket HA (temps réel)
                          i18n.py    (alertes,     ha_client.py ◄── API REST HA
                                     code d'accès)
```

```
Minitel-HA/
├── server.py            # Démarrage, routes HTTP (page, API archives)
├── session.py           # Logique des modes, commune au Minitel et au navigateur
├── hub.py               # Sessions ouvertes, temps réel, alertes, code d'accès
├── pagevideo.py         # Pages Vidéotex (40 x 24 + ligne 0)
├── devices.py           # Comportement par type d'entité
├── ha_client.py         # API REST de Home Assistant
├── ha_live.py           # WebSocket de Home Assistant (temps réel)
├── alerts.py  journal.py  i18n.py  settings.py  utils.py  pagehtml.py
├── ws_minitel.py        # Transport Minitel (:3615)
├── ws_browser.py        # Transport navigateur (:8080/ws)
├── discover.py          # Découverte des entités HA
├── config.example.yaml  # Modèle de configuration
├── static/index.html    # Émulateur Minitel
├── tests/               # Tests (pytest) + faux Home Assistant (tests/fake_ha.py)
└── tools/sync_addon.sh  # Copie du code vers le dépôt de l'add-on
```

---

## 🏠 Installation en add-on Home Assistant (recommandé)

1. **Paramètres** → **Modules complémentaires** → **Boutique** → menu **⋮** → **Dépôts**
2. Ajouter : `https://github.com/Mrt0t0/Minitel-HA-addon`
3. Installer **Minitel-HA**, puis **Démarrer** (aucune option obligatoire)
4. Ouvrir **Minitel** dans la barre latérale de Home Assistant
5. Minitel physique (ESP32 / TelnetPro / Minimit) : `ws://[IP_HA]:3615`

Au premier démarrage, les lampes et prises sont découvertes automatiquement. Le reste (scènes, alertes, capteurs météo, ordre des pièces…) se règle dans `/share/minitel-ha/config.yaml` : voir la [documentation de l'add-on](https://github.com/Mrt0t0/Minitel-HA-addon/blob/main/minitel-ha/DOCS.md).

---

## 🐳 Installation Docker (hors Home Assistant)

Prérequis : Docker + Docker Compose, Home Assistant joignable sur le réseau, un *Long-Lived Access Token* (Profil HA → Sécurité).

```bash
git clone https://github.com/Mrt0t0/Minitel-HA
cd Minitel-HA
cp config.example.yaml config.yaml   # config.yaml n'est pas versionné : il contient votre token
nano config.yaml                      # URL de HA, token, réglages

docker compose run --rm minitel-ha python discover.py   # découverte des entités (facultatif)
docker compose up -d --build
```

- Émulateur : `http://[IP_SERVEUR]:8080`
- Minitel : `ws://[IP_SERVEUR]:3615`
- Mise à jour : `git pull && docker compose up -d --build`
- Journaux : `docker compose logs -f`

Le journal des actions est conservé dans `data/`, les pages `.vdt` dans `static/archives/`.

---

## Configuration (`config.yaml`)

Le modèle complet et commenté est [`config.example.yaml`](config.example.yaml). Principales sections :

```yaml
homeassistant:
  url: http://192.168.1.x:8123
  token: "VOTRE_TOKEN"

display:
  language: fr              # fr | en (écrans et assistant)
  page_size: 9              # appareils par page (1-9)
  show_sensors: true        # mode Capteurs

security:
  access_code: "1234"       # facultatif : demandé sur le Minitel et le navigateur

alerts:                     # ligne 0 du Minitel
  - entity: binary_sensor.porte_entree
    state: "on"
    message: "Porte d'entrée ouverte"
  - entity: sensor.salon_temperature
    above: 28
    message: "Salon trop chaud"

quick_off:                  # touche * en mode Domotique
  entity: scene.tout_eteindre
  name: "Tout éteindre"
  confirm: true

devices:                    # rempli par discover.py, modifiable à la main
  - entity: cover.volet_salon
    name: Volet salon
    area: Salon
```

Types d'appareils gérés : `light`, `switch`, `fan`, `input_boolean`, `automation`, `cover`, `climate`, `media_player`, `lock`, `scene`, `script`, `button` (et tout autre domaine via `homeassistant.toggle`).

### Découverte des entités

```bash
python discover.py            # --dry : aperçu sans écrire ; --force : ignorer les personnalisations
```

Les noms, pièces et visibilités modifiés à la main sont conservés ; les entités disparues de HA sont masquées (`visible: false`). Pour découvrir d'autres types, ajoutez-les à `discovery.domains`.

---

## 🔌 Connexion Minitel physique

Configurer l'ESP32 pour se connecter en WebSocket à `ws://[IP_SERVEUR]:3615`.

- Iodeo (TelnetPro) : https://iodeo.fr/
- Minimit : https://www.multiplie.fr/produit/minimit/

---

## Pages Vidéotex (`.vdt`)

Déposez vos fichiers `.vdt` avec le bouton **`.vdt ⇪`** de l'émulateur, ou copiez-les dans `static/archives/` (Docker) ou `/share/minitel-ha/archives/` (add-on). Consultation depuis le mode `R`.

Sources de pages : [XReyRobert/VideotexPagesRepository](https://github.com/XReyRobert/VideotexPagesRepository) (merci XReyRobert).

API HTTP (avec le code d'accès actif, en-tête `X-Minitel-Token` obtenu après saisie du code) :
`GET /api/archives/list`, `GET /api/archives/vdt/{nom}`, `POST /api/archives/upload` (multipart, champ `file`, 512 Ko max par défaut).

---

## Développement

```bash
pip install -r requirements-dev.txt
ruff check .
pytest -q
python tests/fake_ha.py 8123          # faux Home Assistant (token : test) pour essayer sans HA
```

Le code de l'add-on est une copie de ce dépôt : après modification, `tools/sync_addon.sh` met à jour `Minitel-HA-addon` (sa CI vérifie que les fichiers sont identiques à `main`).

---
---

# English

# Minitel-HA — 3615 MAISON

**Control Home Assistant from a real Minitel (or a web browser) through Videotex.**

| Home control | 24h chart |
|---|---|
| ![Home control](https://raw.githubusercontent.com/Mrt0t0/Minitel-HA/main/screen/v13-domotique.png) | ![Chart](https://raw.githubusercontent.com/Mrt0t0/Minitel-HA/main/screen/v13-graphique.png) |

## Description

Minitel-HA bridges a **physical Minitel** (through an ESP32 / TelnetPro Iodeo or Minimit) and **Home Assistant**. The same Videotex service is available from:

- 🟢 **a real Minitel** connected through an ESP32 (WebSocket, port `:3615`);
- 🌐 **a web browser**: Minitel emulator with a virtual keyboard (port `:8080`, or the HA sidebar with the add-on).

The browser shows exactly the same pages as the Minitel: one logic, one renderer.

## What's new in v1.3

| Area | New |
|---|---|
| **Real time** | Subscribes to the Home Assistant WebSocket: state changes show up immediately and only the affected lines are rewritten (the Minitel runs at 1200 baud). Falls back to polling automatically |
| **Security** | Optional access code (Minitel and browser), 3 attempts per connection, IP blocked after 5 failures. Add-on: access through the HA sidebar (ingress) needs no code |
| **Browser** | Real Minitel emulator: same pages as the Minitel, row 0, accents, cursor, double size. Physical and on-screen (mobile) keyboards |
| **Sensors** | New `C` mode: values by room and a 24h Videotex semi-graphic chart (`Digit + ENVOI`) |
| **Devices** | Covers, thermostats, media players, locks, fans. `SUITE` / `RETOUR` adjust the selected device (brightness, position, setpoint, volume) |
| **Alerts** | Minitel row 0: door open, temperature threshold… (`alerts` in the configuration) |
| **Confirmations** | "All off" (`*`) and unlocking a lock ask for `ENVOI` to confirm |
| **Journal** | Kept on disk across restarts |
| **Language** | Screens in French or English (`display.language`) |
| **Archives** | Upload `.vdt` pages from the browser (`.vdt ⇪` button) |
| **Quality** | One Minitel / browser logic, 36 automated tests, lint and GitHub Actions CI, Docker image built |

## Modes and keys

| Key | Mode |
|---|---|
| `D` | Home control: toggle, adjust, live state |
| `C` | Sensors: values and 24h chart |
| `M` | Weather: forecast and rooms |
| `S` | Scenes and scripts |
| `J` | Journal |
| `A` | Home Assistant AI assistant |
| `R` | `.vdt` archives |
| `H` | Help |

| Minitel key | Browser keyboard | Effect |
|---|---|---|
| Letter | Letter | Change mode |
| `SOMMAIRE` | `Esc` | Main menu |
| `GUIDE` | `F1` | Help |
| `ENVOI` | `Enter` | Confirm |
| `SUITE` / `RETOUR` | `→` / `←` | Next / previous page, or adjust the selected device |
| `CORRECTION` | `Backspace` | Erase |
| `ANNULATION` | `Delete` | Cancel / back |
| `REPETITION` | `F2` | Refresh (assistant: new conversation) |

## 🏠 Home Assistant add-on (recommended)

1. **Settings** → **Add-ons** → **Add-on store** → **⋮** → **Repositories**
2. Add `https://github.com/Mrt0t0/Minitel-HA-addon`
3. Install **Minitel-HA** and **Start** it (no option is required)
4. Open **Minitel** in the Home Assistant sidebar
5. Physical Minitel: `ws://[HA_IP]:3615`

See the [add-on documentation](https://github.com/Mrt0t0/Minitel-HA-addon/blob/main/minitel-ha/DOCS.md) for scenes, alerts and the other settings.

## 🐳 Docker (outside Home Assistant)

```bash
git clone https://github.com/Mrt0t0/Minitel-HA
cd Minitel-HA
cp config.example.yaml config.yaml   # config.yaml is not tracked: it holds your token
nano config.yaml
docker compose run --rm minitel-ha python discover.py   # optional entity discovery
docker compose up -d --build
```

Emulator: `http://[SERVER_IP]:8080` — Minitel: `ws://[SERVER_IP]:3615` — Update: `git pull && docker compose up -d --build`.

## Configuration

See the commented [`config.example.yaml`](config.example.yaml): `display.language`, `security.access_code`, `alerts`, `quick_off.confirm`, `devices`, `sensors`, `meteo`, `assistant`, `archives`, `journal`.
`python discover.py` (`--dry`, `--force`) fills `devices` and `sensors` and keeps your customisations.

## Physical Minitel connection

Configure the ESP32 to connect through WebSocket to `ws://[SERVER_IP]:3615` — [Iodeo](https://iodeo.fr/), [Minimit](https://www.multiplie.fr/produit/minimit/).

## Videotex pages (`.vdt`)

Upload them with the emulator's **`.vdt ⇪`** button or copy them into `static/archives/` (Docker) or `/share/minitel-ha/archives/` (add-on). Sources: [XReyRobert/VideotexPagesRepository](https://github.com/XReyRobert/VideotexPagesRepository).

## Development

```bash
pip install -r requirements-dev.txt
ruff check . && pytest -q
python tests/fake_ha.py 8123          # fake Home Assistant (token: test)
```

The add-on code is a copy of this repository: run `tools/sync_addon.sh` after a change (the add-on CI checks the files match `main`).

---

**Python dependencies:** `aiohttp` `websockets` `pyyaml`
