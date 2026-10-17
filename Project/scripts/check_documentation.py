"""Check the bilingual public-site contract after `mkdocs build --strict`."""

from html.parser import HTMLParser
import json
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

from mkdocs.config import load_config


class PageLinks(HTMLParser):
    def __init__(self, content: str) -> None:
        super().__init__()
        self.locale = None
        self.languages: dict[str, dict[str, str]] = {}
        self.alternates: dict[str, str] = {}
        self.images: list[str] = []
        self.links: list[str] = []
        self.anchors: set[str] = set()
        self.feed(content)

    def handle_starttag(self, tag, attrs) -> None:
        attrs = dict(attrs)
        if tag == "html":
            self.locale = attrs.get("lang")
        if attrs.get("id"):
            self.anchors.add(attrs["id"])
        if tag == "a" and attrs.get("hreflang") in ("en", "ru"):
            self.languages[attrs["hreflang"]] = attrs
        if (tag == "link" and "alternate" in attrs.get("rel", "").split()
                and attrs.get("hreflang") in ("en", "ru")):
            locale = attrs["hreflang"]
            assert locale not in self.alternates, f"Duplicate head alternate: {locale}"
            self.alternates[locale] = attrs["href"]
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])
        if tag == "img" and attrs.get("src"):
            self.images.append(attrs["src"])


def main() -> None:
    project = Path(__file__).resolve().parents[1]
    config = load_config(config_file=str(project / "mkdocs.yml"))
    site = Path(config.site_dir)
    base = config.site_url
    base_url = urlsplit(base)
    pages = sorted(site.rglob("index.html"))
    assert pages, "Build documentation before checking it."
    parsed_pages = {page: PageLinks(page.read_text(encoding="utf-8")) for page in pages}
    for page in pages:
        relative = page.relative_to(site).as_posix().removesuffix("index.html")
        russian = relative.startswith("ru/")
        article = relative.removeprefix("ru/") if russian else relative
        url = base + relative
        content = page.read_text(encoding="utf-8")
        links = parsed_pages[page]
        assert links.locale == ("ru" if russian else "en"), page
        assert set(links.languages) == {"en", "ru"}, page
        assert set(links.alternates) == set(links.languages), (page, "Missing head alternates")
        for locale, attrs in links.languages.items():
            locale_path = ("ru/" if locale == "ru" else "") + article
            expected = base + locale_path
            assert attrs.get("target") == "_self", "Locale changes must reload the translated shell."
            assert urljoin(url, attrs["href"]) == expected, (page, locale)
            assert urljoin(url, links.alternates[locale]) == expected, (page, locale, "Incorrect head alternate")
            assert (site / locale_path / "index.html").is_file(), (page, locale)
            assert (attrs.get("aria-current") == "true") == (locale == ("ru" if russian else "en")), page
        source = "index" if not article else article.rstrip("/")
        translated = (Path(config.docs_dir) / (source + ".ru.md")).is_file()
        assert ("Перевод пока не готов" in content) == (russian and not translated), page
        if russian and translated:
            original = parsed_pages[site / article / "index.html"]
            assert original.anchors <= links.anchors, (page, original.anchors - links.anchors)
        for image in links.images:
            target = urlsplit(urljoin(url, image))
            if target.netloc == base_url.netloc:
                path = unquote(target.path.removeprefix(base_url.path))
                assert (site / path).is_file(), (page, image)
        for href in links.links:
            target = urlsplit(urljoin(url, href))
            if target.netloc != base_url.netloc or not target.path.startswith(base_url.path):
                continue
            path = site / unquote(target.path.removeprefix(base_url.path))
            if path.is_dir():
                path /= "index.html"
            assert path.is_file(), (page, href, "Missing internal destination")
            if target.fragment and path.suffix == ".html":
                destination = parsed_pages.get(path)
                if destination is None:
                    destination = PageLinks(path.read_text(encoding="utf-8"))
                assert unquote(target.fragment) in destination.anchors, (page, href, "Missing anchor")

    for excluded in ("raw", "overrides", "_drafts", "_templates", ".obsidian", "troubleshooting"):
        assert not (site / excluded).exists(), excluded
        assert not (site / "ru" / excluded).exists(), excluded
    assert not (site / "wiki/project-overview").exists(), "Engineering wiki leaked."
    search = json.loads((site / "search/search_index.json").read_text(encoding="utf-8"))
    assert {"en", "ru"} <= set(search["config"]["lang"]), "Bilingual search configuration missing."
    for location in ("", "ru/"):
        assert any(doc["location"] == location for doc in search["docs"]), f"Search page missing: {location}"
    assert not any("troubleshooting/faq" in doc["location"] for doc in search["docs"]), "Hidden FAQ is searchable."
    print(f"Bilingual documentation contract and internal links passed: {len(pages)} pages.")


if __name__ == "__main__":
    main()
