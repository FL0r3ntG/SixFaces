# Six-Faces (`six_faces`)

Ground News for Quebec, personal project. Runs on the laptop as the Podman quadlet `six-faces` on port 8010.
README.md documents the design, the evaluation and how to run it. The **UI is in French**; code, comments
and docs are in English.

## Status (2026-10-11)

- Collection (21 outlets), enrichment, same-owner copy detection, grouping into events and chained sujets,
  verification, ranking and all pages work. The service collects continuously since 2026-10-11.
- Grouping uses the fitted pair probabilities in `app/nlp/similarity.py` and the constants at the top of
  `app/cluster.py`. After any change to them, run `uv run python eval/evaluate.py`, compare with the README
  table, then `scripts/recluster.py` (service stopped). Never tune by eye on the live pages.

## Rules

- **No LLM** for grouping or categorizing (the user's choice). The local embedding model + rules + fitted
  weights is the approach.
- **Never bypass bot protection** (captcha, WAF, Cloudflare, Akamai). Blocked outlets stay headline-only
  (`fetch_pages=False`, Google News). Respect robots.txt and `HOST_DELAY_S`.
- Corroboration counts **ownership groups**, never sites; agency copy is never an independent confirmation.
- **Never show a duplicate.** Same-owner copies (`dup_of`) are excluded from everything (`views.canonical()`).
  The same piece run by another owner (`same_as`) is excluded from lists and article counts
  (`views.listed()`) but keeps its owner's credit in coverage (`canonical()`). New queries that list
  articles must use `listed()`; name outlets with `views.outlet()` (it adds "+ other outlet").
- Stories are chains: a development links to the closest *earlier* development (`Event.follows_id`); one
  development spans at most `MAX_SPAN` (24 h).
- **Look**: a newspaper front page. Newsreader for headlines, Inter for UI, hairline rules and columns,
  editorial red `--brand` used sparingly. No emojis, no rounded cards, no gradients, no badge boxes
  (status is a text mark, outlets are small caps with a colour square).
- **Colours**: one colour per ownership group, everywhere, following the outlets' branding (slots `--s1…--s8`,
  order in `views.CHART_GROUPS`, alternating reds and blues for stacking). Groups without a brand colour
  fold into "Autres". Re-check separation (normal + colour-blind, both themes) before changing a colour.
- Never put scraped text (titles, summaries) inside `data-tip` attributes: app.js renders them as HTML.
- No logo: the cube reference stays implicit in the name. The app name and tagline live in `app/config.py` (`app_name`, `app_tagline`); templates use `APP_NAME`.
- Only one process may run the scheduler on `data/six_faces.db`.

## Commands

```bash
uv run pytest && uv run ruff check . && uv run ruff format .
podman build -t localhost/six-faces:latest . && systemctl --user restart six-faces
journalctl --user -u six-faces -f
uv run python eval/evaluate.py
systemctl --user stop six-faces && uv run python -m scripts.recluster && systemctl --user start six-faces
```
