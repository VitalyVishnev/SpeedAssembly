"""Check the bilingual public-site contract after `mkdocs build --strict`."""

from html.parser import HTMLParser
import json
from pathlib import Path
from urllib.parse import urljoin, urlsplit


class PageLinks(HTMLParser):
    def __init__(self, content: str) -> None:
        super().__init__()
        self.languages: dict[str, dict[str, str]] = {}
        self.images: list[str] = []
        self.anchors: set[str] = set()
        self.feed(content)

    def handle_starttag(self, tag, attrs) -> None:
        attrs = dict(attrs)
        if attrs.get("id"):
            self.anchors.add(attrs["id"])
        if tag == "a" and attrs.get("hreflang") in ("en", "ru"):
            self.languages[attrs["hreflang"]] = attrs
        if tag == "img" and attrs.get("src"):
            self.images.append(attrs["src"])


def main() -> None:
    project = Path(__file__).resolve().parents[1]
    site = project / "site"
    base = "https://vitalyvishnev.github.io/SpeedAssembly/"
    pages = sorted(site.rglob("index.html"))
    assert pages, "Build documentation before checking it."
    for page in pages:
        relative = page.relative_to(site).as_posix().removesuffix("index.html")
        russian = relative.startswith("ru/")
        article = relative.removeprefix("ru/") if russian else relative
        url = base + relative
        content = page.read_text(encoding="utf-8")
        links = PageLinks(content)
        assert set(links.languages) == {"en", "ru"}, page
        for locale, attrs in links.languages.items():
            locale_path = ("ru/" if locale == "ru" else "") + article
            expected = base + locale_path
            assert urljoin(url, attrs["href"]) == expected, (page, locale)
            assert (site / locale_path / "index.html").is_file(), (page, locale)
            assert (attrs.get("aria-current") == "true") == (locale == ("ru" if russian else "en")), page
        source = "index" if not article else article.rstrip("/")
        translated = (project / "docs/user" / (source + ".ru.md")).is_file()
        assert ("Перевод пока не готов" in content) == (russian and not translated), page
        if russian and translated:
            original = PageLinks((site / article / "index.html").read_text(encoding="utf-8"))
            assert original.anchors <= links.anchors, (page, original.anchors - links.anchors)
        for image in links.images:
            target = urlsplit(urljoin(url, image))
            if target.netloc == urlsplit(base).netloc:
                path = target.path.removeprefix("/SpeedAssembly/")
                assert (site / path).is_file(), (page, image)

    for excluded in ("raw", "overrides", "_drafts", "_templates", ".obsidian", "troubleshooting"):
        assert not (site / excluded).exists(), excluded
        assert not (site / "ru" / excluded).exists(), excluded
    assert not (site / "wiki/project-overview").exists(), "Engineering wiki leaked."
    search = json.loads((site / "search/search_index.json").read_text(encoding="utf-8"))
    assert {"en", "ru"} <= set(search["config"]["lang"]), "Bilingual search configuration missing."
    for location in ("", "ru/"):
        assert any(doc["location"] == location for doc in search["docs"]), f"Search page missing: {location}"
    assert not any("troubleshooting/faq" in doc["location"] for doc in search["docs"]), "Hidden FAQ is searchable."
    print(f"Bilingual documentation contract passed: {len(pages)} pages.")


if __name__ == "__main__":
    main()
