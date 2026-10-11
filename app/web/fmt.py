"""Jinja filters: French dates in Quebec time, relative times, labels."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.models import utcnow
from app.nlp.categories import CATEGORIES

TZ = ZoneInfo(get_settings().display_tz)
MONTHS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
DAYS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]

STATUS = {
    # status: (label, css class, icon, explanation)
    "confirme": ("Confirmé", "good", "✓", "Rapporté par au moins 3 groupes de presse indépendants"),
    "corrobore": ("Corroboré", "ok", "≈", "Rapporté par 2 groupes de presse indépendants"),
    "source_unique": ("Source unique", "warn", "!", "Un seul groupe de presse le rapporte pour l'instant"),
    "depeche": (
        "Dépêche seulement",
        "warn",
        "↻",
        "Seulement de la copie d'agence (PC, AFP…), aucun reportage propre",
    ),
}


def local(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(TZ)


def hm(dt: datetime | None) -> str:
    return local(dt).strftime("%H h %M") if dt else ""


def day(dt: datetime | None) -> str:
    if not dt:
        return ""
    d = local(dt)
    return f"{DAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]}"


def when(dt: datetime | None) -> str:
    """'14 h 05' today, 'sam. 10 oct., 14 h 05' otherwise."""
    if not dt:
        return ""
    if local(dt).date() == local(utcnow()).date():
        return hm(dt)
    return f"{day(dt)}, {hm(dt)}"


def ago(dt: datetime | None) -> str:
    if not dt:
        return "jamais"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    s = (utcnow() - dt).total_seconds()
    if s < 90:
        return "à l'instant"
    if s < 3600:
        return f"il y a {int(s // 60)} min"
    if s < 86400:
        return f"il y a {int(s // 3600)} h"
    d = int(s // 86400)
    return f"il y a {d} jour{'s' if d > 1 else ''}"


def hours(h: float) -> str:
    if h < 1 / 60:
        return "0 min"
    if h < 1:
        return f"+{round(h * 60)} min"
    if h < 48:
        return f"+{h:.0f} h" if h >= 10 else f"+{h:.1f} h".replace(".", ",")
    return f"+{h / 24:.0f} j"


CAT_ICONS = {
    "politique": "🏛️", "economie": "💼", "sante": "🩺", "education": "🎓", "justice": "⚖️",
    "environnement": "🌿", "international": "🌍", "societe": "🏘️", "culture": "🎭", "sports": "🏒",
    "techno": "🔬",
}  # fmt: skip
LONG_DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
LONG_MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
               "novembre", "décembre"]  # fmt: skip


def dayname(d) -> str:
    """date -> 'samedi 10 octobre'"""
    return f"{LONG_DAYS[d.weekday()]} {d.day}{'er' if d.day == 1 else ''} {LONG_MONTHS[d.month - 1]}"


def caticon(key: str | None) -> str:
    return CAT_ICONS.get(key or "", "📰")


def longdate(dt: datetime) -> str:
    d = local(dt)
    return f"{LONG_DAYS[d.weekday()].capitalize()} {d.day}{'er' if d.day == 1 else ''} {LONG_MONTHS[d.month - 1]} {d.year}"


def greeting(dt: datetime) -> str:
    h = local(dt).hour
    return "Bonne nuit" if h < 5 else "Bonjour" if h < 18 else "Bonsoir"


def category(key: str | None) -> str:
    return CATEGORIES.get(key or "", "Société")


def plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def register(env) -> None:
    env.filters.update(
        hm=hm,
        day=day,
        when=when,
        ago=ago,
        hours=hours,
        category=category,
        local=local,
        plural=plural,
        caticon=caticon,
        longdate=longdate,
        dayname=dayname,
    )
    env.globals.update(
        STATUS=STATUS,
        CATEGORIES=CATEGORIES,
        APP_NAME=get_settings().app_name,
        APP_TAGLINE=get_settings().app_tagline,
    )
