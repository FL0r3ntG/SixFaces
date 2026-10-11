from datetime import UTC, datetime

from app.fetch.discover import keep, parse_gnews, parse_rss, parse_sitemap
from app.sources import BY_KEY

# Québecor uses https:// namespaces, most others http:// — both must parse
SITEMAP_HTTPS = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="https://www.sitemaps.org/schemas/sitemap/0.9" xmlns:news="https://www.google.com/schemas/sitemap-news/0.9">
  <url><loc>https://www.journaldemontreal.com/2026/10/11/trump-annonce</loc>
    <news:news><news:publication><news:name>JdM</news:name></news:publication>
      <news:publication_date>2026-10-11T10:41:55-04:00</news:publication_date>
      <news:title>Trump annonce un «cessez-le-feu énergétique»</news:title><news:keywords></news:keywords>
    </news:news></url>
</urlset>""".encode()

SITEMAP_HTTP = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">
  <url><loc>https://montrealgazette.com/news/man-stabbed</loc>
    <news:news><news:publication_date>2026-10-11T10:27:00Z</news:publication_date>
      <news:title>Man stabbed in Pierrefonds-Roxboro early Sunday</news:title>
      <news:keywords>Crime, Police</news:keywords></news:news></url>
  <url><loc>https://montrealgazette.com/no-title</loc></url>
</urlset>"""

RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>
<item><title>Exclu de la CAQ, Mathieu Lacombe s&#8217;excuse</title><link>https://www.ledevoir.com/politique/1/x</link>
<pubDate>Fri, 09 Oct 2026 08:15:00 -0400</pubDate><author>L&#233;o Mercier-Ross</author><category>Qu&#233;bec</category>
<description>&lt;p&gt;Le d&#233;put&#233; s&#8217;est excus&#233;.&lt;/p&gt;</description></item>
<item><title>No date</title><link>https://x/y</link></item>
</channel></rss>"""

GNEWS = """<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Courses de rue | La police met fin à un rassemblement - La Presse</title>
<link>https://news.google.com/rss/articles/abc</link><pubDate>Sun, 11 Oct 2026 11:44:34 GMT</pubDate>
<description>whatever</description></item>
<item><title> - La Presse</title><link>https://news.google.com/rss/articles/empty</link>
<pubDate>Sun, 11 Oct 2026 11:44:34 GMT</pubDate></item>
</channel></rss>""".encode()


def test_sitemap_https_namespace_and_timezone():
    [c] = parse_sitemap(SITEMAP_HTTPS)
    assert c.title == "Trump annonce un «cessez-le-feu énergétique»"
    assert c.published_at == datetime(2026, 10, 11, 14, 41, 55, tzinfo=UTC)


def test_sitemap_http_namespace_keywords_and_incomplete_entries():
    found = parse_sitemap(SITEMAP_HTTP)
    assert [c.url for c in found] == ["https://montrealgazette.com/news/man-stabbed"]
    assert found[0].tags == ["Crime", "Police"]


def test_rss_cleans_html_and_skips_undated():
    [c] = parse_rss(RSS, featured=True)
    assert c.title == "Exclu de la CAQ, Mathieu Lacombe s’excuse"
    assert c.summary == "Le député s’est excusé."
    assert c.author == "Léo Mercier-Ross" and c.tags == ["Québec"] and c.featured


def test_gnews_strips_outlet_and_drops_empty_items():
    [c] = parse_gnews(GNEWS, ("La Presse",), "sports")
    assert c.title == "Courses de rue | La police met fin à un rassemblement"
    assert c.summary == "" and c.tags == ["sports"]


def test_keep_filters_urls_and_junk_titles():
    [c] = parse_sitemap(SITEMAP_HTTPS)
    assert keep(BY_KEY["jdm"], c)
    c.title = "Avis légaux - 10 octobre 2026"
    assert not keep(BY_KEY["jdm"], c)
    c.title, c.url = "Un vrai titre", "https://www.ctvnews.ca/toronto/article/x"
    assert not keep(BY_KEY["ctv"], c)  # CTV: Montreal section only
