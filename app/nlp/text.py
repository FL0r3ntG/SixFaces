"""Rule-based text handling (no LLM): normalization, wire/opinion detection, key terms."""

import html
import re
import unicodedata

_WS = re.compile(r"\s+")
_TAGS = re.compile(r"<[^>]+>")


def clean(s: str | None) -> str:
    if not s:
        return ""
    return _WS.sub(" ", html.unescape(_TAGS.sub(" ", s))).strip()


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def normalize(s: str) -> str:
    """Lowercase, no accents, no punctuation: for comparing titles."""
    s = strip_accents(s.lower())
    s = re.sub(r"[^\w\s]", " ", s)
    return _WS.sub(" ", s).strip()


# Google News appends " - La Presse"; some feeds prefix "EN DIRECT |" or "VIDÉO |"
_TITLE_PREFIX = re.compile(
    r"^\s*((EN DIRECT|EXCLUSIF|VIDÉO|VIDEO|PHOTOS?|AUDIO|LIVE|BREAKING|ANALYSE|CHRONIQUE|ÉDITORIAL)\s*[|:–-]\s*)+",
    re.IGNORECASE,
)


def clean_title(title: str, outlet_suffixes: tuple[str, ...] = ()) -> str:
    t = clean(title)
    for suffix in outlet_suffixes:
        for sep in (" - ", " – ", " | "):
            t = t.removesuffix(sep + suffix)
    return _TITLE_PREFIX.sub("", t).strip()


# --- wire copy -------------------------------------------------------------------------------------------

_WIRE_PATTERNS = (
    ("PC", re.compile(r"presse canadienne|canadian press", re.IGNORECASE)),
    ("AFP", re.compile(r"agence france[- ]presse|\bAFP\b")),
    ("Reuters", re.compile(r"\breuters\b", re.IGNORECASE)),
    ("AP", re.compile(r"associated press|\bthe associated\b|\(AP\)", re.IGNORECASE)),
)


def detect_wire(author: str | None, text: str | None) -> str | None:
    """Agency name if the byline, or the dateline at the top of the text, credits a news agency."""
    for agency, pat in _WIRE_PATTERNS:
        if author and pat.search(author):
            return agency
    head = (text or "")[:300]
    for agency, pat in _WIRE_PATTERNS:
        if pat.search(head):
            return agency
    return None


# --- opinion ---------------------------------------------------------------------------------------------

_OPINION_URL = re.compile(
    r"/(opinions?|chroniques?|debats|editorial|editoriaux|columnists?|blogues?|lettres?|"
    r"point-de-vue|carrefour-des-lecteurs|libre-opinion|analyses?)(/|$)",
    re.IGNORECASE,
)
_OPINION_TAG = re.compile(
    r"\b(opinion|chronique|éditorial|editorial|column|lettre|libre opinion|analyse)s?\b", re.IGNORECASE
)


def detect_opinion(url: str, section: str | None, tags: list[str] | None = None) -> bool:
    if _OPINION_URL.search(url):
        return True
    return any(_OPINION_TAG.search(t) for t in [section or "", *(tags or [])])


# --- key terms -------------------------------------------------------------------------------------------

_STOPWORDS = """
    a au aux avec ce ces cet cette dans de des du elle elles en et eux il ils je la le les leur leurs lui ma mais
    me meme mes moi mon ne nos notre nous on ou par pas pour qu que qui sa se ses son sur ta te tes toi ton tu un
    une vos votre vous y d l j m n s t c qu est sont ete etre avoir a ont plus moins tres tout tous toute toutes
    apres avant selon sans sous entre depuis pendant contre vers chez lors alors aussi ainsi donc car si comme
    deja encore fait faire font peut peuvent doit doivent dit dire va vont nouveau nouvelle nouveaux nouvelles
    premier premiere deux trois an ans annee annees jour jours semaine fois quebec montreal
    the a an and or of to in on for with at by from as is are was were be been has have had it its this that
    these those he she they his her their not but after before over under into about than more new says said
    will would could can may also up out who what when where why how all one two three year years week day
"""
STOPWORDS = set(_STOPWORDS.split())

_TOKEN = re.compile(r"[\w'’-]+", re.UNICODE)
_CAPSEQ = re.compile(
    r"(?<![\w])((?:[A-ZÀ-Ý][\w'’-]+)(?:\s+(?:de |du |des |la |le |d’|d')?[A-ZÀ-Ý][\w'’-]+)*)"
)


_SUFFIXES = (
    "ements",
    "ement",
    "ations",
    "ation",
    "euses",
    "euse",
    "eurs",
    "eur",
    "ives",
    "ive",
    "ies",
    "es",
    "s",
    "e",
)


def _stem(w: str) -> str:
    """Very light suffix stripping, good enough to match plurals/feminine forms in FR and EN."""
    for suf in _SUFFIXES:
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def terms(text: str) -> list[str]:
    """Content-word stems of a text, accents removed, stopwords dropped."""
    out = []
    for tok in _TOKEN.findall(strip_accents(text.lower())):
        tok = tok.strip("'’-")
        if "'" in tok or "’" in tok:  # l'enquete -> enquete
            tok = re.split(r"['’]", tok)[-1]
        if len(tok) < 3 or tok in STOPWORDS or tok.isdigit():
            continue
        out.append(_stem(tok))
    return out


# Capitalized words that start sentences/headlines but are not names
_STARTER_WORDS = """
    Le La Les L Un Une Des Du De Ce Cet Cette Ces Il Elle Ils Elles On Nous Vous Je Pourquoi Comment Quand Où Qui
    Que Quoi Quel Quelle Quels Quelles Voici Voilà Après Avant Pour Sans Avec Selon Malgré Depuis Pendant Encore
    Plus Moins Bilan Mort Morts Décès Enquête Retour Fin Début Nouveau Nouvelle Nouveaux Nouvelles Deux Trois Au
    Aux En Et Mais Ou Si Dans Sur Sous Vers Chez Entre Contre Face Grâce Hausse Baisse Tout Tous Toute Toutes
    The A An In On At Of For With How Why What When Who This That These Those New After Before More Less
"""
_STARTERS = {normalize(w) for w in _STARTER_WORDS.split()}
_DETERMINER = re.compile(r"^(le|la|les|l|the|un|une|des|du|de|d|au|aux)\s+")


def entities(text: str) -> set[str]:
    """Capitalized sequences (names, places, organisations), normalized, leading article removed:
    "Les Houthis" and "aux Houthis" both give "houthis"."""
    found = set()
    for sentence in re.split(r"(?<=[.!?:«»\"|;])\s+|\n", text):
        for m in _CAPSEQ.finditer(sentence):
            norm = _DETERMINER.sub("", normalize(m.group(1)))
            if " " not in norm and (norm in _STARTERS or (m.start() == 0 and norm in STOPWORDS)):
                continue
            if len(norm) >= 3 and norm not in STOPWORDS and norm not in _STARTERS:
                found.add(norm)
    return found


def entity_tokens(text: str) -> set[str]:
    """Words of the names in a text ("max verstappen" -> {"max", "verstappen"}), for partial name matches."""
    return {w for e in entities(text) for w in e.split() if len(w) >= 3 and w not in STOPWORDS}
