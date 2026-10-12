# Déployer Six-Faces sur un serveur

Ce guide permet à n'importe qui de mettre Six-Faces en ligne sur son propre serveur, sans connaître le
projet. Compter environ 30 minutes, plus le temps de propagation du DNS.

Une fois en ligne, le site est **public** (sans connexion), **en lecture seule** et **non indexé** par les
moteurs de recherche. Il collecte les médias tout seul toutes les 15 minutes.

- [1. Ce qu'il faut](#1-ce-quil-faut)
- [2. Pointer le domaine vers le serveur](#2-pointer-le-domaine-vers-le-serveur)
- [3. Préparer le serveur](#3-préparer-le-serveur)
- [4. Installer Six-Faces](#4-installer-six-faces)
- [5. Vérifier que tout fonctionne](#5-vérifier-que-tout-fonctionne)
- [6. Au quotidien](#6-au-quotidien)
- [7. Reprendre des données existantes](#7-reprendre-des-données-existantes)
- [8. Dépannage](#8-dépannage)
- [9. Réglages](#9-réglages)
- [10. Ce que le site fait et ne fait pas](#10-ce-que-le-site-fait-et-ne-fait-pas)

---

## 1. Ce qu'il faut

| | Minimum | Confortable |
|---|---|---|
| Serveur Linux allumé 24 h/24 (Ubuntu 22.04+ ou Debian 12+ dans ce guide) | 2 processeurs, **4 Go de mémoire** | 4 processeurs, 8 Go |
| Disque libre | 8 Go | 20 Go |
| Ports ouverts vers Internet | 80 et 443 (TCP), 443 (UDP) | |
| Un nom de domaine (ou sous-domaine) | dont tu peux modifier le DNS | |

La mémoire compte : deux modèles d'analyse du texte tournent sur le serveur (environ 3 Go en tout). Avec
moins de 4 Go, le serveur risque de manquer de mémoire.

N'importe quel hébergeur convient (Hetzner, OVH, DigitalOcean, Scaleway…). Choisir un serveur
« VPS » ou « cloud server » avec la mémoire indiquée et un système Ubuntu ou Debian.

Il faut aussi un accès SSH au serveur : `ssh utilisateur@adresse-du-serveur`.

## 2. Pointer le domaine vers le serveur

Chez le fournisseur du domaine (là où se gère son DNS), créer :

| Type | Nom | Valeur |
|---|---|---|
| `A` | le sous-domaine voulu, par ex. `nouvelles` (ou `@` pour le domaine nu) | l'adresse IPv4 du serveur |
| `AAAA` (si le serveur a une IPv6) | le même nom | l'adresse IPv6 du serveur |

Vérifier, depuis n'importe quel ordinateur, que le domaine répond avec l'adresse du serveur (cela peut
prendre de quelques minutes à quelques heures) :

```bash
dig +short nouvelles.example.com
```

**Ne pas passer à l'étape 4 avant que cette commande renvoie l'adresse du serveur** : le certificat HTTPS
ne peut pas être obtenu sinon.

## 3. Préparer le serveur

Se connecter au serveur, puis :

```bash
# Mises à jour du système
sudo apt update && sudo apt upgrade -y

# Docker et Docker Compose (script d'installation officiel de Docker)
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"     # utiliser docker sans sudo
# se déconnecter puis se reconnecter pour que ce changement prenne effet

# Vérifier
docker --version && docker compose version

# Pare-feu : n'ouvrir que SSH, HTTP et HTTPS
sudo apt install -y ufw sqlite3 git
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443
sudo ufw enable
```

Si un autre site utilise déjà les ports 80 et 443 sur ce serveur, voir le [dépannage](#ports-80-ou-443-déjà-utilisés).

## 4. Installer Six-Faces

```bash
git clone https://github.com/FL0r3ntG/SixFaces.git six-faces
cd six-faces

# Configuration : seule la ligne DOMAIN est obligatoire
cp deploy/server/.env.example deploy/server/.env
nano deploy/server/.env        # remplacer nouvelles.example.com par ton domaine

# Construire et démarrer (la première construction prend quelques minutes)
docker compose -f deploy/server/compose.yaml up -d --build
```

Au **premier démarrage** :
1. Caddy obtient un certificat HTTPS pour le domaine (quelques secondes).
2. L'application télécharge ses deux modèles d'analyse dans `data/models` (environ 3 Go, quelques minutes).
3. La collecte commence : les premiers articles arrivent dans les minutes qui suivent, et les premiers
   sujets apparaissent après la première passe de regroupement (environ 10 à 20 minutes).

La page d'accueil affiche « La collecte démarre » tant qu'il n'y a rien à montrer : c'est normal.

## 5. Vérifier que tout fonctionne

```bash
# Les deux services tournent (STATUS « Up »)
docker compose -f deploy/server/compose.yaml ps

# Suivre l'application : on doit voir « scheduler started », puis des lignes « … new (rss) » et « clustered … »
docker compose -f deploy/server/compose.yaml logs -f app

# Le site répond en HTTPS (code 200) et n'est pas indexé
curl -sI https://nouvelles.example.com | grep -iE "^HTTP|x-robots-tag|strict-transport"
```

Puis ouvrir `https://nouvelles.example.com` dans un navigateur. La page **Sources** indique l'état de
chaque média : après une heure, tous devraient être « OK ».

Sur téléphone, le site peut s'ajouter à l'écran d'accueil (« Ajouter à l'écran d'accueil » sur iPhone,
« Installer l'application » sur Android) : il s'ouvre alors en plein écran, comme une application.

## 6. Au quotidien

Toutes les commandes se lancent depuis le dossier `six-faces`.

```bash
# Mettre à jour vers la dernière version
git pull
docker compose -f deploy/server/compose.yaml up -d --build

# Journaux
docker compose -f deploy/server/compose.yaml logs -f app      # application
docker compose -f deploy/server/compose.yaml logs -f caddy    # HTTPS / accès

# Redémarrer / arrêter
docker compose -f deploy/server/compose.yaml restart app
docker compose -f deploy/server/compose.yaml down              # arrête tout (les données restent)

# Mémoire et processeur utilisés
docker stats --no-stream
```

**Sauvegarde.** Tout l'état du site est dans `data/six_faces.db` (les modèles de `data/models` se
retéléchargent). Les fichiers de `data/` appartiennent à `root` (le conteneur tourne en root), d'où le
`sudo`. Une sauvegarde cohérente peut se faire pendant que le site tourne :

```bash
sudo sqlite3 data/six_faces.db ".backup sauvegarde-$(date +%F).db"
```

Par exemple chaque nuit à 3 h, en gardant 14 jours (`sudo crontab -e`, en adaptant le chemin) :

```
0 3 * * * cd /home/utilisateur/six-faces && mkdir -p sauvegardes && sqlite3 data/six_faces.db ".backup sauvegardes/$(date +\%F).db" && find sauvegardes -name '*.db' -mtime +14 -delete
```

**Restaurer** : arrêter (`down`), remplacer `data/six_faces.db` par la sauvegarde
(`sudo cp sauvegardes/AAAA-MM-JJ.db data/six_faces.db`), redémarrer (`up -d`).

## 7. Reprendre des données existantes

Pour démarrer avec l'historique d'une installation existante (par exemple un ordinateur qui collectait
déjà), arrêter d'abord la collecte sur la machine d'origine, puis copier son dossier `data` :

```bash
# 1. sur le serveur : arrêter l'application et rendre le dossier data modifiable par ton utilisateur
docker compose -f deploy/server/compose.yaml stop app
sudo mkdir -p data && sudo chown -R "$USER" data

# 2. sur la machine d'origine, collecte arrêtée
rsync -a --info=progress2 data/ utilisateur@adresse-du-serveur:six-faces/data/

# 3. sur le serveur
docker compose -f deploy/server/compose.yaml start app
```

Copier `data/models` aussi évite de retélécharger les 3 Go de modèles. **Un seul collecteur doit tourner** :
deux installations qui collectent en même temps doublent les requêtes envoyées aux médias.

## 8. Dépannage

### Le site ne s'ouvre pas en HTTPS / erreur de certificat
- Vérifier que `dig +short ton.domaine` renvoie bien l'adresse du serveur.
- Vérifier que les ports 80 et 443 sont ouverts (`sudo ufw status`, et le pare-feu de l'hébergeur s'il y en a un).
- Lire `docker compose -f deploy/server/compose.yaml logs caddy` : Caddy y explique pourquoi le certificat échoue.
- Après correction : `docker compose -f deploy/server/compose.yaml restart caddy`.

### Ports 80 ou 443 déjà utilisés
Un autre serveur web (nginx, Apache, un autre Caddy) occupe déjà les ports. Deux possibilités :
- Ajouter Six-Faces à ce serveur web existant : retirer le service `caddy` de `compose.yaml`, publier
  l'application sur un port local (`ports: ["127.0.0.1:8010:8000"]` à la place de `expose`), et faire
  pointer le domaine vers `http://127.0.0.1:8010` dans la configuration du serveur web existant.
- Ou arrêter l'autre serveur web s'il ne sert plus.

### L'application redémarre en boucle ou est « Killed »
Manque de mémoire. Vérifier avec `docker stats --no-stream` et `dmesg | grep -i kill`. Il faut au moins
4 Go de mémoire ; à défaut, ajouter de l'espace d'échange (swap) de 4 Go :

```bash
sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

### Rien n'apparaît après une heure
- `docker compose -f deploy/server/compose.yaml logs app | grep -iE "error|traceback"` montre les erreurs.
- La page **Sources** montre quels médias échouent. Certains hébergeurs ont des adresses IP que des
  médias bloquent : cela touche quelques médias, pas le site entier.
- Le premier téléchargement des modèles peut échouer si le disque est plein (`df -h`).

### Revenir à une version précédente
```bash
git log --oneline | head          # repérer la version voulue
git checkout <identifiant>
docker compose -f deploy/server/compose.yaml up -d --build
# revenir à la dernière version : git checkout main && git pull
```

## 9. Réglages

Les réglages se mettent dans `deploy/server/.env` (voir `deploy/server/.env.example`), puis
`docker compose -f deploy/server/compose.yaml up -d` pour les appliquer.

| Réglage | Par défaut | Rôle |
|---|---|---|
| `DOMAIN` | — (obligatoire) | Domaine du site ; Caddy obtient le certificat HTTPS pour lui |
| `ALLOW_INDEXING` | `false` | `true` laisse les moteurs de recherche indexer le site |
| `APP_NAME` | `Six-Faces` | Nom affiché dans l'en-tête et les titres |
| `APP_TAGLINE` | `La presse québécoise, sous toutes ses faces` | Slogan sous le nom |
| `DISPLAY_TZ` | `America/Toronto` | Fuseau horaire d'affichage des heures |
| `DISCOVER_INTERVAL_MINUTES` | `15` | Fréquence de lecture des flux RSS et sitemaps |
| `GNEWS_INTERVAL_MINUTES` | `30` | Fréquence des requêtes Google News (La Presse, L'actualité) |
| `PROCESS_INTERVAL_MINUTES` | `5` | Fréquence du regroupement et du classement |
| `HOST_DELAY_S` | `2.0` | Écart minimal entre deux requêtes vers un même média |

`PUBLIC_MODE` est toujours actif sur le serveur (fixé dans `compose.yaml`) : un site public est en lecture
seule.

## 10. Ce que le site fait et ne fait pas

- **Lecture seule** : un visiteur ne peut rien modifier ni déclencher. Le bouton *Actualiser* et son
  action sont désactivés ; les détails d'erreurs internes sont masqués ; il n'y a pas d'explorateur d'API.
- **Non indexé** par défaut : `robots.txt` interdit l'exploration, et chaque page porte
  `X-Robots-Tag: noindex`. Quiconque a l'adresse peut tout de même consulter le site.
- **HTTPS** obligatoire, avec en-têtes de sécurité (HSTS, anti-cadre, anti-détournement de type).
- **Collecte respectueuse** : le site respecte le `robots.txt` de chaque média, ne contourne aucune
  protection (captcha, pare-feu applicatif), espace ses requêtes et s'identifie comme usage personnel non
  commercial.
- **Contenu des médias** : les titres, de courts chapeaux et les photos des médias sont affichés avec un
  lien vers l'article original ; les photos sont chargées depuis les serveurs des médias, jamais copiées.
  Un média peut demander le retrait de son contenu : supprimer sa ligne dans `app/sources.py` arrête la
  collecte de ce média.
