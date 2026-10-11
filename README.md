# Six-Faces

*La presse québécoise, sous toutes ses faces.*

Six-Faces is a personal, Quebec-only take on Ground News. Every 15 minutes it collects the articles of
**21 Quebec outlets** (French and English) and groups them:
- into **events**, one news development as covered by every outlet;
- into **sujets**, a story followed over days as a chain of developments.

It then compares **who covers what, how, and how fast**. It runs on the laptop, the interface is in
French, and it uses **no generative AI**: grouping relies on a small local embedding model plus rules and
weights fitted on hand-labelled examples.

- [What you see](#what-you-see)
- [Sources and ownership groups](#sources-and-ownership-groups)
- [How it works](#how-it-works)
- [Evaluation](#evaluation)
- [Running it](#running-it)
- [Development](#development)
- [Project layout](#project-layout)
- [Known limits](#known-limits)

## What you see

| Page | Contents |
|---|---|
| **À la une** `/` | A newspaper-style front page. Masthead with the edition date; the day in figures (articles, active media, sujets, confirmed stories, share of coverage by group); *Dernière heure*; three columns: **Le fil** (every new article as it arrives), the **lead story** with "Comment ils titrent" (the same news headlined by other groups), and the next stories; **Le titre qui divise** (the event that groups word most differently); **Angle mort du jour** (a big story a major group did not cover); one block per section. |
| **Tous les sujets** `/?vue=liste` | Every sujet ranked by importance, filterable by period (24 h → 30 days) and section, with coverage bar, other outlets' headlines, missing major groups and 48 h activity. |
| **Sujet** `/sujet/{id}` | One story. Photo and lede, key figures, who covers it, *course à la nouvelle* (each group's first article and delay), volume chart, **évolution jour par jour**, then the **chronologie**. Each development shows its verification, which earlier development it follows from ("↳ Fait suite à …") and diverging figures. Its articles, grouped by owner, stay folded until you open one or click *Afficher tous les articles*. |
| **Couverture** `/couverture` | Share of each section in each group's coverage (heatmap), blind spots per group, who publishes first. |
| **Sources** `/sources` | Health of every outlet's feeds, articles per day, page fetching, and *Actualiser maintenant*. |
| **Recherche** `/recherche?q=` | Search in headlines and summaries. |

Status marks: **✓ Confirmé** means at least 3 independent ownership groups have their own article.
**≈ Corroboré** means 2. **! Source unique** means 1. **↻ Dépêche seulement** means agency copy only.
This measures corroboration, not truth.

## Sources and ownership groups

| Access | Outlets |
|---|---|
| Full text (feed or news sitemap + article page) | Le Devoir, Radio-Canada, CBC Montreal, the six CN2i papers (Le Soleil, Le Droit, La Tribune, Le Nouvelliste, Le Quotidien, La Voix de l'Est), Montreal Gazette, CTV Montréal, Noovo Info, 98.5 Montréal, Métro, Pivot |
| Headline + feed summary (article pages answer "Access Denied") | Le Journal de Montréal, Le Journal de Québec, TVA Nouvelles |
| Headline via Google News (whole site behind a captcha) | La Presse (one query per section), L'actualité |

- **No protection is bypassed.** Blocked outlets stay headline-only. robots.txt is respected for article
  pages: the Gazette forbids its RSS feed but allows its news sitemap, so the sitemap is used. There is
  a 2 s gap between two requests to the same host, and the user agent identifies the app.
- Full article text is stored locally for analysis only. The UI shows headlines, short ledes and links
  to the originals. Photos are the outlets' own lead images, hotlinked (`no-referrer`), never downloaded.
- **Corroboration counts ownership groups, not sites.** The groups are Québecor (JdM, JdQ, TVA), CN2i
  (6 papers), CBC/Radio-Canada, Bell Média (CTV, Noovo), Postmedia (Gazette), La Presse, Le Devoir,
  Cogeco (98.5), Métro Média, Pivot and Mishmash (L'actualité).
- **Same-owner copies count once.** When a group republishes one piece on several of its sites (JdM →
  JdQ, TVA; Le Soleil → the other CN2i papers), the first one is kept. The others point to it
  (`Article.dup_of`) and are left out of every count, ranking, vote, chart and list. The UI shows the
  piece once, as "Québecor · 3 sites : …". On the first two days that was 408 of 670 Québecor articles
  and 368 of 515 CN2i articles. A copy has the same owner, appears within 48 h, and has the same
  headline or an embedding cosine ≥ 0.96.
- **The same piece from another owner shows once too.** Agency copy (La Presse Canadienne, AFP, AP,
  Reuters) is often run word for word by different owners: Noovo Info and L'actualité, CN2i and Le
  Devoir. Such an article points to the first one (`Article.same_as`) when its headline is the same once
  normalized: rubric prefix dropped ("Guerre en Ukraine | …"), one containing the other, or ≥ 90 %
  similar. It also has to appear within 36 h and be close in meaning. It is forced into the same
  development, listed once with "+ L'actualité", and counted once as an article. Each owner still gets
  credit in the coverage bars, because it chose to run the story. Two outlets' *own* articles on the same
  news are never merged this way.
- **Agency copy** is detected from bylines, datelines and identical headlines across groups. It never
  counts as an independent confirmation.
- **Colours**: each group has one colour, used everywhere (charts, dots, outlet labels). Colours follow
  the outlets' branding: Radio-Canada, La Presse and CN2i in red; Québecor, Bell (Noovo) and the Gazette
  in blue; Le Devoir grey; Métro green. Groups sharing a colour family get distinct shades, and the
  stacked bars alternate reds and blues. The palette was checked for normal and colour-blind vision in
  both themes (`app/web/static/app.css`, `--s1…--s8`).

## How it works

```
scheduler (APScheduler; catches up after the laptop sleeps)
 ├─ discover:<source>  every 15 min (Google News 30 min)  RSS / news sitemaps / Google News → Article
 ├─ enrich             every 3 min   article page → text, byline, section, photo (trafilatura)
 ├─ images             every 4 min   og:image for articles whose feed has no photo
 └─ process            every 5 min
      ├─ cluster   embed headline + lede → same-owner copies → join an event or start one
      │            → merge split events → link each development to the story it continues
      ├─ verify    independent groups, agency copy, diverging figures
      └─ rank      importance of events and sujets
```

### Same event? Same story?

Each pair of articles gets three numbers:
- `cos`, the cosine of their embeddings (headline + start of lede; multilingual, so French and English
  coverage of the same news land close together);
- `lex`, the IDF-weighted overlap of word stems, with names counting double;
- `hours`, how far apart they were published.

Two logistic models, fitted on hand-labelled pairs (see [Evaluation](#evaluation)), turn these into
probabilities (`app/nlp/similarity.py`):

```
p_event = σ(−2.74 + 4.63·cos + 8.05·lex − 1.10·ln(1 + hours))   same development
p_story = σ(−5.53 + 7.25·cos + 9.33·lex)                        same story, any development
```

Time matters for events: same-development pairs are a median 3.8 h apart, other developments of the
same story 21 h. It doesn't matter for stories, which run for days.

`app/cluster.py` uses them like this:
- **Joining an event.** The best match in the event must reach 0.6 and the second best 0.3, so one
  stray link is not enough. Time is counted from the event's *start*, and a development spans at most
  24 h. Inside one development, coverage cannot drift article by article.
- **Merge pass.** Two events started less than 24 h apart whose three best cross pairs average ≥ 0.7 are
  fused. This repairs events split by the order articles arrived in.
- **Stories are chains.** A new development joins the sujet of the *earlier* development it is closest
  to (mean of its two best pairs, `p_story` ≥ 0.7). It is compared with every development of the last 7
  days, not with where the story began, and the link is stored (`Event.follows_id`, `follows_p`). The
  first and last developments can have little in common as long as each step is close: *Trump négocie du
  diesel russe* → *Poutine reçoit les propositions* → *un nouveau président pour l'Ukraine* →
  *cessez-le-feu énergétique*.
- **Sports.** Sujets only chain coverage of the same game, otherwise every Canadiens game would join
  one endless story.
- The **headline of an event** is its most consensual one, the closest to all the others. Opinion
  pieces, very short headlines and live-blog lines are avoided ("Première période | …").

### Importance, sections, figures

- **Importance:** the sum over ownership groups of freshness × weight × (1 + 0.15 · ln(articles)).
  Freshness has an 18 h half-life. Opinion-only coverage counts ×0.5, agency-only ×0.6, and a
  front-page feed (*à la une*, *manchettes*) adds 0.5. A sujet scores its best development plus
  0.3 × the others. Sports and culture are damped on the front page.
- **Sections:** the outlet's own section is trusted when it exists (URL, the feed it came from,
  Radio-Canada's "Zone X" bylines). Otherwise headline keywords give a weak guess, which the 7 nearest
  well-labelled articles can overrule. An event's section is one vote per ownership group, so six CN2i
  papers filing the same wire under *affaires* count once.
- **Figures:** death tolls, injuries, evacuations and arrests are extracted with patterns and compared
  across outlets with their times. A toll that rises over the day is usually an update, not a
  contradiction, and the page says so.

## Evaluation

`eval/pairs.json` holds 313 cross-outlet article pairs, labelled by hand blind to the algorithm's output:
**E** for same event, **S** for same story but another development, **N** for unrelated. They were
sampled across the whole similarity range, plus pairs the algorithm put together and close pairs it kept
apart.

```bash
uv run python eval/evaluate.py                 # re-clusters a COPY of the database and scores it
uv run python eval/evaluate.py P_SUJET=0.6     # try another value of any app.cluster constant
```

It reports pairwise precision, recall and F1 for "same event" and "same sujet", and the largest sujets.
Pair metrics don't catch a sujet that swallows unrelated developments; size does.

| 1 776 articles, 2026-10-11 | Same event P / R / F1 | Same sujet P / R / F1 | Largest sujet |
|---|---|---|---|
| First version (fixed thresholds on `cos + 0.6·lex`) | 0.74 / 0.53 / 0.62 | 0.95 / 0.76 / 0.84 | 12 (a post-election catch-all) |
| Fitted probabilities + merge pass | 0.82 / 0.88 / 0.85 | 0.94 / 0.89 / 0.92 | 5 |
| + time from the event start, 24 h span, chained stories (**current**) | **0.88 / 0.83 / 0.86** | **0.93 / 0.88 / 0.90** | 6 |

The pair models were 5-fold cross-validated. Headline-only similarity, named-entity overlap and
language added about 0.01 F1 and were left out. Most remaining errors are judgment calls: a sprint vs
the Grand Prix, a statement vs the reply to it. With a few weeks of data, label more pairs (especially
long-running stories) and refit.

## Running it

It runs like appart_finder: a Podman container managed by a systemd user service (a *quadlet*), on
<http://127.0.0.1:8010>. It starts with the session and restarts if it crashes. The data (SQLite and the
~1 GB embedding model, downloaded on first start) lives in `data/`, mounted at `/data`.

```bash
# first install
podman build -t localhost/six-faces:latest .
cp deploy/six-faces.container ~/.config/containers/systemd/
systemctl --user daemon-reload
systemctl --user start six-faces

# day to day
systemctl --user {status,restart,stop} six-faces
journalctl --user -u six-faces -f

# after a code change
podman build -t localhost/six-faces:latest . && systemctl --user restart six-faces
```

Database migrations run at startup. **Only one process may run the scheduler on `data/six_faces.db`**,
so stop the service before running the app another way:

```bash
uv sync
uv run uvicorn app.main:app --port 8010                                    # full app, scheduler on
SCHEDULER_ENABLED=false uv run uvicorn app.main:app --port 8011 --reload   # UI only (service may stay up)
```

After changing similarity, clustering, copy detection or section rules, rebuild the grouping. Articles
and embeddings are kept:

```bash
systemctl --user stop six-faces && uv run python -m scripts.recluster && systemctl --user start six-faces
```

Settings go in `.env` or the environment (`app/config.py`): `APP_NAME`, `APP_TAGLINE`, collection
intervals, `HOST_DELAY_S`, `EMBEDDING_MODEL`, `DISPLAY_TZ` (default America/Toronto).

## Development

```bash
uv run pytest                                     # offline: parsers, NLP rules, verification, ranking, pages
uv run ruff check . && uv run ruff format .
uv run alembic revision --autogenerate -m "..."   # after changing app/models.py
uv run python eval/evaluate.py                    # after touching grouping
```

**Adding an outlet** takes one entry in `app/sources.py`: its feeds (`rss`, `sitemap` or `gnews`), owner
group, language, and `fetch_pages=False` if article pages are blocked. Read its robots.txt first. A new
owner group needs a label in `GROUPS`; it shows as "Autres" unless it gets a colour slot (`CHART_GROUPS`
in `app/web/views.py` and `--sN` in `app.css`).

## Project layout

```
app/
  sources.py        the 21 outlets: feeds, owner group, access mode, URL filters
  fetch/            http.py (polite client, robots.txt) · discover.py (RSS / sitemaps / Google News) ·
                    enrich.py (article page → text, byline, photo)
  ingest.py         store new articles, merge duplicates across feeds, enrich pages, backfill photos
  nlp/              text.py (cleaning, names, wire & opinion detection) · categories.py (sections) ·
                    embed.py (local ONNX model) · similarity.py (lexical overlap, p_event, p_story)
  cluster.py        copies → events → merge pass → story chains; event headline and section
  verify.py         independent groups, agency copy, diverging figures
  rank.py           importance of events and sujets
  scheduler.py      background jobs, catch-up after sleep
  models.py         Article → Event → Sujet, FetchRun
  web/              routes.py · views.py (queries for each page) · fmt.py (French dates) · templates/ · static/
eval/               pairs.json (labelled pairs) · evaluate.py
scripts/            recluster.py
migrations/         Alembic
deploy/             six-faces.container (Podman quadlet)
tests/              offline test suite
```

**Data model.** An `Article` belongs to one `Event` (one development) and may be a same-owner copy of
another article (`dup_of`). An `Event` belongs to one `Sujet` (a story) and records the earlier event it
follows from (`follows_id`, `follows_p`). `FetchRun` logs every feed fetch for the Sources page. All
times are stored in UTC and shown in Quebec time.

## Known limits

- La Presse and L'actualité are headline-only, through Google News, which caps each feed at 100 items
  (hence one query per La Presse section). Their times can lag a little.
- Québecor gives a headline and a short summary only, so its text never feeds figure checks or wire
  detection.
- "Premier à publier" relies on each outlet's published time, which some outlets update when they edit.
- Grouping was tuned on the first days of collection. Re-check it with `eval/evaluate.py` as data
  accumulates.
- If the laptop is off for more than about a day, Google News items from the gap are lost (the queries
  look back one day). RSS feeds and sitemaps cover about two days.

## The name

**Six-Faces** sounds like a Quebec place name (Trois-Rivières, Deux-Montagnes, Sept-Îles), but it is the
six faces of a cube: each face one outlet's angle on the same story. The reference stays implicit, so
there is no logo, just the name.

## License

GPL-3.0-only, like appart_finder.
