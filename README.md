# Six-Faces

*La presse québécoise, sous toutes ses faces.*

Six-Faces est un Ground News personnel, entièrement consacré au Québec. Toutes les 15 minutes, il collecte
les articles de **21 médias québécois** (francophones et anglophones) et les regroupe :
- en **événements** : un même développement de l'actualité, tel que couvert par chaque média ;
- en **sujets** : une histoire suivie sur plusieurs jours, comme une chaîne de développements.

Il compare ensuite **qui couvre quoi, comment et à quelle vitesse**. Il tourne sur le portable, l'interface
est en français, et il n'utilise **aucune IA générative** : le regroupement repose sur des modèles
d'embeddings locaux, des règles et des pondérations ajustées sur des exemples étiquetés à la main.

- [Ce qu'on y voit](#ce-quon-y-voit)
- [Sources et groupes de presse](#sources-et-groupes-de-presse)
- [Fonctionnement](#fonctionnement)
- [Évaluation](#évaluation)
- [Lancer l'application](#lancer-lapplication)
- [Développement](#développement)
- [Organisation du code](#organisation-du-code)
- [Limites connues](#limites-connues)

## Ce qu'on y voit

| Page | Contenu |
|---|---|
| **À la une** `/` | Une une de journal. En-tête avec la date de l'édition ; la journée en chiffres (articles, médias actifs, sujets, nouvelles confirmées, part de la couverture par groupe) ; *Dernière heure* ; trois colonnes : **Le fil** (chaque nouvel article dès son arrivée), la **nouvelle principale** avec « Comment ils titrent » (la même nouvelle titrée par les autres groupes) et les nouvelles suivantes ; **Le titre qui divise** (l'événement que les groupes formulent le plus différemment) ; **Angle mort du jour** (une grosse nouvelle qu'un grand groupe n'a pas couverte) ; un bloc par rubrique. |
| **Tous les sujets** `/?vue=liste` | Tous les sujets classés par importance, filtrables par période (24 h → 30 jours) et par rubrique, avec la barre de couverture, les titres des autres médias, les grands groupes absents et l'activité sur 48 h. |
| **Sujet** `/sujet/{id}` | Une histoire. Photo et chapeau, chiffres clés, qui en parle, *course à la nouvelle* (premier article de chaque groupe et délai), volume de couverture, **évolution jour par jour**, puis la **chronologie**. Chaque développement affiche sa vérification, le développement antérieur dont il découle (« ↳ Fait suite à … ») et les chiffres divergents. Ses articles, regroupés par propriétaire, restent repliés jusqu'à ce qu'on en ouvre un ou qu'on clique sur *Afficher tous les articles*. |
| **Couverture** `/couverture` | Part de chaque rubrique dans la couverture de chaque groupe (carte de chaleur), angles morts par groupe, qui publie en premier. |
| **Sources** `/sources` | État des flux de chaque média, articles par jour, lecture des pages, et *Actualiser maintenant*. |
| **Recherche** `/recherche?q=` | Recherche dans les titres et les résumés. |

Mentions de vérification : **✓ Confirmé** = au moins 3 groupes de presse indépendants ont leur propre
article. **≈ Corroboré** = 2. **! Source unique** = 1. **↻ Dépêche seulement** = uniquement de la copie
d'agence. Cela mesure la corroboration, pas la vérité.

## Sources et groupes de presse

| Accès | Médias |
|---|---|
| Texte complet (flux ou sitemap news + page de l'article) | Le Devoir, Radio-Canada, CBC Montreal, les six journaux de CN2i (Le Soleil, Le Droit, La Tribune, Le Nouvelliste, Le Quotidien, La Voix de l'Est), Montreal Gazette, CTV Montréal, Noovo Info, 98.5 Montréal, Métro, Pivot |
| Titre + résumé du flux (les pages répondent « Access Denied ») | Le Journal de Montréal, Le Journal de Québec, TVA Nouvelles |
| Titre via Google News (tout le site derrière un captcha) | La Presse (une requête par rubrique), L'actualité |

- **Aucune protection n'est contournée.** Les médias bloqués restent en « titre seul ». Le robots.txt est
  respecté pour les pages d'articles : la Gazette interdit son flux RSS mais autorise son sitemap news,
  c'est donc le sitemap qui est utilisé. Deux requêtes vers un même site sont espacées d'au moins 2 s,
  et le user agent identifie l'application.
- Le texte des articles est conservé localement, uniquement pour l'analyse. L'interface montre les
  titres, de courts chapeaux et des liens vers les originaux. Les photos sont celles des médias,
  affichées depuis leurs serveurs (`no-referrer`), jamais téléchargées.
- **La corroboration compte des groupes de presse, pas des sites.** Les groupes : Québecor (JdM, JdQ,
  TVA), CN2i (6 journaux), CBC/Radio-Canada, Bell Média (CTV, Noovo), Postmedia (Gazette), La Presse,
  Le Devoir, Cogeco (98.5), Métro Média, Pivot et Mishmash (L'actualité).
- **Les reprises d'un même propriétaire comptent une seule fois.** Quand un groupe republie un article
  sur plusieurs de ses sites (JdM → JdQ, TVA ; Le Soleil → les autres journaux de CN2i), seul le premier
  est gardé. Les autres pointent vers lui (`Article.dup_of`) et sont exclus de tous les comptes,
  classements, votes, graphiques et listes. L'interface affiche l'article une fois, sous la forme
  « Québecor · 3 sites : … ». Les deux premiers jours, cela représentait 408 des 670 articles de Québecor
  et 368 des 515 de CN2i. Une reprise a le même propriétaire, paraît dans les 48 h, et a le même titre
  ou une similarité d'embedding ≥ 0,96.
- **Le même article chez un autre propriétaire n'apparaît aussi qu'une fois.** La copie d'agence (La
  Presse Canadienne, AFP, AP, Reuters) est souvent reprise mot pour mot par des propriétaires différents :
  Noovo Info et L'actualité, CN2i et Le Devoir. Un tel article pointe vers le premier (`Article.same_as`)
  quand son titre est identique une fois normalisé : préfixe de rubrique retiré (« Guerre en Ukraine | … »),
  l'un contenant l'autre, ou similaire à ≥ 90 %. Il doit aussi paraître dans les 36 h et être proche par
  le sens. Il est placé dans le même développement, affiché une fois avec « + L'actualité » et compté
  comme un seul article. Chaque propriétaire reste crédité dans les barres de couverture, puisqu'il a
  choisi de publier la nouvelle. Les articles *propres* de deux médias sur la même nouvelle ne sont
  jamais fusionnés de cette façon.
- **La copie d'agence** est repérée par la signature, la mention de lieu et les titres identiques entre
  groupes. Elle ne compte jamais comme une confirmation indépendante.
- **Couleurs** : chaque groupe a une couleur, la même partout (graphiques, pastilles, noms de médias),
  qui suit l'identité visuelle des médias : Radio-Canada, La Presse et CN2i en rouge ; Québecor, Bell
  (Noovo) et la Gazette en bleu ; Le Devoir en gris ; Métro en vert. Les groupes d'une même famille de
  couleur ont des teintes distinctes, et les barres empilées alternent rouges et bleus. La palette a été
  vérifiée pour la vision normale et le daltonisme, dans les deux thèmes (`app/web/static/app.css`,
  `--s1…--s8`).

## Fonctionnement

```
planificateur (APScheduler ; rattrape les tâches après la mise en veille du portable)
 ├─ discover:<source>  toutes les 15 min (Google News 30 min)  RSS / sitemaps news / Google News → Article
 ├─ enrich             toutes les 3 min   page de l'article → texte, signature, rubrique, photo (trafilatura)
 ├─ images             toutes les 4 min   og:image pour les articles dont le flux n'a pas de photo
 └─ process            toutes les 5 min
      ├─ cluster   embeddings titre + chapeau → reprises → rattacher à un événement ou en créer un
      │            → fusionner les événements scindés → relier chaque développement à l'histoire qu'il prolonge
      ├─ verify    groupes indépendants, copie d'agence, chiffres divergents
      └─ rank      importance des événements et des sujets
```

### Même événement ? Même histoire ?

Deux modèles d'embeddings multilingues locaux lisent le titre et le début du chapeau, de sorte que les
couvertures française et anglaise d'une même nouvelle se retrouvent proches :
- un modèle **rapide** (`paraphrase-multilingual-mpnet`), pour trouver les candidats, repérer les
  reprises et voter sur les rubriques ;
- un modèle **plus puissant** (`multilingual-e5-large`, environ 0,3 s par article sur le processeur),
  pour décider à quelle histoire appartient un développement.

Chaque paire d'articles reçoit alors :
- `cos` et `e5`, la similarité de leurs deux embeddings ;
- `lex`, le recouvrement des racines de mots pondéré par l'IDF, les noms propres comptant double ;
- `heures`, l'écart entre leurs publications ;
- quand les deux articles ont leur texte : la part de **chiffres** en commun et le recouvrement du
  **vocabulaire du corps** de l'article.

Deux modèles logistiques, ajustés sur des paires étiquetées à la main (voir [Évaluation](#évaluation)),
en font des probabilités (`app/nlp/similarity.py`) :

```
p_event = σ(−2,74 + 4,63·cos + 8,05·lex − 1,10·ln(1 + heures))               même développement
p_story = σ(−60,42 + 69,86·e5 + 3,56·lex [− 2,38 + 3,07·chiffres + 4,36·corps])   même histoire
```

Le temps compte pour les événements : les paires d'un même développement sont publiées à 3,8 h d'écart
en médiane, les autres développements d'une même histoire à 21 h. Il ne compte pas pour les histoires,
qui durent des jours. Le modèle plus puissant et les signaux du corps de l'article aident beaucoup pour
les histoires. Pour les événements, ils ont été essayés et n'apportaient rien à précision égale :
la décision d'événement garde donc le modèle rapide.

`app/cluster.py` les utilise ainsi :
- **Rattacher un article à un événement.** La meilleure correspondance dans l'événement doit atteindre
  0,6 et la deuxième 0,3 : un seul lien isolé ne suffit pas. Le temps est compté depuis le *début* de
  l'événement, et un développement dure au plus 24 h. À l'intérieur d'un développement, la couverture ne
  peut pas dériver d'article en article.
- **Passe de fusion.** Deux événements commencés à moins de 24 h d'intervalle, dont les trois meilleures
  paires croisées atteignent en moyenne 0,7, sont fusionnés. Cela répare les événements scindés à cause
  de l'ordre d'arrivée des articles.
- **Les histoires sont des chaînes.** Un nouveau développement rejoint le sujet du développement
  *antérieur* dont il est le plus proche (moyenne de ses deux meilleures paires, `p_story` ≥ 0,7). Il est
  comparé à tous les développements des 7 derniers jours, pas au point de départ de l'histoire, et le lien
  est conservé (`Event.follows_id`, `follows_p`). Le premier et le dernier développement peuvent avoir
  peu en commun, tant que chaque étape est proche : *Trump négocie du diesel russe* → *Poutine reçoit les
  propositions* → *un nouveau président pour l'Ukraine* → *cessez-le-feu énergétique*.
- **Sports.** Un sujet n'enchaîne que la couverture d'un même match ; sinon, tous les matchs du Canadien
  formeraient une seule histoire sans fin.
- Le **titre d'un événement** est le plus consensuel, le plus proche de tous les autres. Les opinions, les
  titres très courts et les lignes de direct (« Première période | … ») sont évités.

### Importance, rubriques, chiffres

- **Importance** : somme, sur les groupes de presse, de fraîcheur × poids × (1 + 0,15 · ln(articles)).
  La fraîcheur a une demi-vie de 18 h. Une couverture faite seulement d'opinions compte ×0,5, seulement
  de copie d'agence ×0,6, et la présence dans un fil « à la une » ou « manchettes » ajoute 0,5. Un sujet
  vaut son meilleur développement plus 0,3 × les autres. Les sports et la culture sont atténués à la une.
- **Rubriques** : la rubrique du média fait foi quand elle existe (URL, flux d'origine, signatures « Zone X »
  de Radio-Canada). Sinon, des mots-clés du titre donnent une estimation faible, que peuvent corriger les
  7 articles bien étiquetés les plus proches. La rubrique d'un événement se décide à une voix par groupe de
  presse : six journaux de CN2i qui classent la même dépêche en *affaires* ne comptent qu'une fois.
- **Chiffres** : les bilans (morts, blessés, évacués, arrestations) sont extraits par motifs et comparés
  d'un média à l'autre, avec l'heure. Un bilan qui monte au fil de la journée est le plus souvent une mise
  à jour, pas une contradiction, et la page le dit.

## Évaluation

`eval/pairs.json` contient 510 paires d'articles de médias différents, étiquetées à la main sans voir le
résultat de l'algorithme : **E** pour même événement, **S** pour même histoire mais autre développement,
**N** pour sans rapport. Le champ `set` distingue deux échantillons :
- `spread` (313 paires) : tirées sur toute l'échelle de similarité, plus des paires que l'algorithme
  regroupait et des paires proches qu'il séparait ;
- `recall` (197 paires) : des paires que la version précédente gardait **séparées**. 28 étaient le même
  développement et 61 la même histoire.

```bash
uv run python eval/evaluate.py                 # regroupe une COPIE de la base et la note
uv run python eval/evaluate.py P_SUJET=0.6     # essayer une autre valeur d'une constante de app.cluster
EVAL_DB=/chemin/copie.db uv run python eval/evaluate.py   # partir d'une copie dont les embeddings
                                                          # sont déjà calculés (bien plus rapide)
```

Le script donne la précision, le rappel et le F1 par paire pour « même événement » et « même sujet »,
pour l'ensemble et pour chaque échantillon, ainsi que la taille des plus gros sujets. Les mesures par
paire ne repèrent pas un sujet qui avale des développements sans rapport ; sa taille, si.

| 1 776 articles, 11 octobre 2026, 313 paires | Même événement P / R / F1 | Même sujet P / R / F1 | Plus gros sujet |
|---|---|---|---|
| Première version (seuils fixes sur `cos + 0,6·lex`) | 0,74 / 0,53 / 0,62 | 0,95 / 0,76 / 0,84 | 12 (un fourre-tout post-électoral) |
| Probabilités ajustées + passe de fusion | 0,82 / 0,88 / 0,85 | 0,94 / 0,89 / 0,92 | 5 |
| + temps compté depuis le début, 24 h max, histoires en chaîne | 0,88 / 0,83 / 0,86 | 0,93 / 0,88 / 0,90 | 6 |

Sur les 510 paires et les mêmes données (1 836 articles) :

| 510 paires | Même événement P / R / F1 | Même sujet P / R / F1 | Plus gros sujet |
|---|---|---|---|
| Version précédente | 0,88 / 0,70 / 0,78 | 0,94 / 0,76 / 0,84 | 6 |
| e5-large aussi pour les événements (meilleur réglage à précision égale) | 0,89 / 0,66 / 0,76 | 0,96 / 0,82 / 0,88 | 6 |
| **Actuelle** : modèle rapide pour les événements ; e5-large + corps de l'article pour les histoires | **0,88 / 0,70 / 0,78** | **0,95 / 0,83 / 0,89** | 6 |

Sur les paires que la version précédente gardait séparées, le rappel des histoires est passé de 0,49 à
0,65. Les modèles de paires ont été validés par validation croisée (5 plis × 3). La similarité des seuls
titres, le recouvrement des entités nommées, la langue et la similarité du corps n'apportaient plus rien
une fois le reste en place. La plupart des erreurs restantes sont des cas limites : l'avant-match et le
résultat, le sprint et le Grand Prix, une déclaration et la réponse à cette déclaration.

## Lancer l'application

Elle tourne dans un conteneur Podman géré par un service systemd utilisateur (un
*quadlet*), sur <http://127.0.0.1:8010>. Elle démarre avec la session et redémarre en cas de plantage. Les
données (SQLite et les deux modèles d'embeddings, environ 3 Go, téléchargés au premier démarrage) sont dans
`data/`, monté sur `/data`.

```bash
# première installation
podman build -t localhost/six-faces:latest .
cp deploy/six-faces.container ~/.config/containers/systemd/
systemctl --user daemon-reload
systemctl --user start six-faces

# au quotidien
systemctl --user {status,restart,stop} six-faces
journalctl --user -u six-faces -f

# après une modification du code
podman build -t localhost/six-faces:latest . && systemctl --user restart six-faces
```

Les migrations de la base s'exécutent au démarrage. **Un seul processus peut faire tourner le
planificateur sur `data/six_faces.db`** : arrêter le service avant de lancer l'application autrement.

```bash
uv sync
uv run uvicorn app.main:app --port 8010                                    # application complète
SCHEDULER_ENABLED=false uv run uvicorn app.main:app --port 8011 --reload   # interface seule (le service peut rester actif)
```

Après une modification de la similarité, du regroupement, de la détection des reprises ou des règles de
rubriques, reconstruire le regroupement. Les articles et les embeddings sont conservés :

```bash
systemctl --user stop six-faces && uv run python -m scripts.recluster && systemctl --user start six-faces
```

Les réglages se mettent dans `.env` ou dans l'environnement (`app/config.py`) : `APP_NAME`, `APP_TAGLINE`,
intervalles de collecte, `HOST_DELAY_S`, `EMBEDDING_MODEL` (modèle rapide), `MATCHING_MODEL` (le modèle qui
décide même événement / même histoire), `DISPLAY_TZ` (par défaut America/Toronto).

## Développement

```bash
uv run pytest                                     # hors ligne : parseurs, règles NLP, vérification, classement, pages
uv run ruff check . && uv run ruff format .
uv run alembic revision --autogenerate -m "..."   # après une modification de app/models.py
uv run python eval/evaluate.py                    # après toute modification du regroupement
```

**Ajouter un média** demande une entrée dans `app/sources.py` : ses flux (`rss`, `sitemap` ou `gnews`), son
groupe propriétaire, sa langue, et `fetch_pages=False` si ses pages d'articles sont bloquées. Lire d'abord
son robots.txt. Un nouveau groupe a besoin d'un libellé dans `GROUPS` ; il apparaît dans « Autres » tant
qu'il n'a pas de couleur (`CHART_GROUPS` dans `app/web/views.py` et `--sN` dans `app.css`).

Le code, les commentaires et les noms restent en anglais ; l'interface et la documentation sont en
français.

## Organisation du code

```
app/
  sources.py        les 21 médias : flux, groupe propriétaire, mode d'accès, filtres d'URL
  fetch/            http.py (client poli, robots.txt) · discover.py (RSS / sitemaps / Google News) ·
                    enrich.py (page d'article → texte, signature, photo)
  ingest.py         enregistre les nouveaux articles, fusionne les doublons entre flux, lit les pages, complète les photos
  nlp/              text.py (nettoyage, noms, détection de dépêches et d'opinions) · categories.py (rubriques) ·
                    embed.py (modèles ONNX locaux) · similarity.py (recouvrement lexical, p_event, p_story)
  cluster.py        reprises → événements → passe de fusion → chaînes d'histoires ; titre et rubrique d'un événement
  verify.py         groupes indépendants, copie d'agence, chiffres divergents
  rank.py           importance des événements et des sujets
  scheduler.py      tâches de fond, rattrapage après la veille
  models.py         Article → Event → Sujet, FetchRun
  web/              routes.py · views.py (requêtes de chaque page) · fmt.py (dates en français) · templates/ · static/
eval/               pairs.json (paires étiquetées) · evaluate.py
scripts/            recluster.py
migrations/         Alembic
deploy/             six-faces.container (quadlet Podman)
tests/              tests hors ligne
```

**Modèle de données.** Un `Article` appartient à un `Event` (un développement). Il peut être une reprise
d'un autre article du même propriétaire (`dup_of`) ou le même article publié par un autre propriétaire
(`same_as`). Un `Event` appartient à un `Sujet` (une histoire) et garde le développement antérieur dont il
découle (`follows_id`, `follows_p`). `FetchRun` trace chaque lecture de flux pour la page Sources. Toutes
les heures sont stockées en UTC et affichées à l'heure du Québec.

## Limites connues

- La Presse et L'actualité sont en « titre seul », via Google News, qui limite chaque flux à 100 éléments
  (d'où une requête par rubrique de La Presse). Leurs heures peuvent avoir un léger retard.
- Québecor ne fournit qu'un titre et un court résumé : son texte n'alimente jamais la vérification des
  chiffres ni la détection des dépêches.
- « Premier à publier » repose sur l'heure de publication de chaque média, que certains modifient quand
  ils mettent un article à jour.
- Le regroupement a été réglé sur les premiers jours de collecte. Le revérifier avec `eval/evaluate.py` à
  mesure que les données s'accumulent.
- Si le portable reste éteint plus d'environ une journée, les articles Google News de cette période sont
  perdus (les requêtes remontent une journée). Les flux RSS et les sitemaps couvrent environ deux jours.

## Le nom

**Six-Faces** sonne comme un nom de lieu québécois (Trois-Rivières, Deux-Montagnes, Sept-Îles), mais ce
sont les six faces d'un cube : chaque face, l'angle d'un média sur la même nouvelle. La référence reste
implicite, il n'y a donc pas de logo, seulement le nom.

## Licence

GPL-3.0-only.
