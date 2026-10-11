# Six-Faces (`six_faces`)

Ground News pour le Québec, projet personnel. Tourne sur le portable avec le quadlet Podman `six-faces`, port 8010.
README.md décrit la conception, l'évaluation et le lancement. **L'interface et la documentation (README,
CLAUDE.md, messages de commit au besoin) sont en français** ; le code, les commentaires et les noms restent en
anglais.

## État (11 octobre 2026)

- Collecte (21 médias), lecture des pages, détection des reprises, regroupement en événements et en sujets
  chaînés, vérification, classement et toutes les pages fonctionnent. Le service collecte en continu depuis le
  11 octobre 2026.
- Le regroupement utilise les probabilités de paires de `app/nlp/similarity.py` et les constantes en tête de
  `app/cluster.py` : les événements utilisent l'embedding rapide, les histoires e5-large (`Article.embedding_e5`)
  plus les chiffres et le vocabulaire du corps. `eval/pairs.json` contient 510 paires étiquetées (`set` :
  spread / recall) ; `EVAL_DB=` fait tourner l'évaluation sur une copie dont les embeddings sont déjà
  calculés. Après toute modification de ces éléments : `uv run python eval/evaluate.py`, comparer au tableau
  du README, puis `scripts/recluster.py` (service arrêté). Ne jamais régler « à l'œil » sur les pages en ligne.

## Règles

- **Pas de LLM** pour regrouper ou classer (choix de l'utilisateur). L'approche : embeddings locaux + règles
  + pondérations ajustées.
- **Ne jamais contourner une protection anti-robots** (captcha, WAF, Cloudflare, Akamai). Les médias bloqués
  restent en titre seul (`fetch_pages=False`, Google News). Respecter robots.txt et `HOST_DELAY_S`.
- La corroboration compte des **groupes de presse**, jamais des sites ; la copie d'agence n'est jamais une
  confirmation indépendante.
- **Ne jamais afficher de doublon.** Les reprises d'un même propriétaire (`dup_of`) sont exclues de tout
  (`views.canonical()`). Le même article publié par un autre propriétaire (`same_as`) est exclu des listes et
  des comptes d'articles (`views.listed()`), mais reste crédité à son propriétaire dans la couverture
  (`canonical()`). Toute nouvelle requête qui liste des articles doit utiliser `listed()` ; nommer les médias
  avec `views.outlet()` (qui ajoute « + autre média »).
- Les histoires sont des chaînes : un développement se rattache au développement *antérieur* le plus proche
  (`Event.follows_id`) ; un développement dure au plus `MAX_SPAN` (24 h).
- **Allure** : une une de journal. Newsreader pour les titres, Inter pour l'interface, filets fins et
  colonnes, rouge éditorial `--brand` utilisé avec parcimonie. Pas d'emojis, pas de cartes arrondies, pas de
  dégradés, pas de badges encadrés (le statut est une mention texte, les médias sont en petites capitales
  avec un carré de couleur).
- **Couleurs** : une couleur par groupe de presse, partout, selon l'identité des médias (emplacements
  `--s1…--s8`, ordre dans `views.CHART_GROUPS`, rouges et bleus alternés pour l'empilement). Les groupes sans
  couleur propre vont dans « Autres ». Revérifier la distinction (vision normale + daltonisme, deux thèmes)
  avant de changer une couleur.
- Ne jamais mettre de texte collecté (titres, résumés) dans un attribut `data-tip` : app.js l'affiche en HTML.
- Pas de logo : la référence au cube reste implicite dans le nom. Le nom et le slogan sont dans
  `app/config.py` (`app_name`, `app_tagline`) ; les gabarits utilisent `APP_NAME`.
- Un seul processus peut faire tourner le planificateur sur `data/six_faces.db`.

## Commandes

```bash
uv run pytest && uv run ruff check . && uv run ruff format .
podman build -t localhost/six-faces:latest . && systemctl --user restart six-faces
journalctl --user -u six-faces -f
uv run python eval/evaluate.py
systemctl --user stop six-faces && uv run python -m scripts.recluster && systemctl --user start six-faces
```
