"""Turning a Tiki API response into the 6 fields the project keeps."""
import re
from html.parser import HTMLParser


class _TextExtractor(HTMLParser):
    """Collect the text of an HTML fragment; tags become spaces, entities are decoded."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_starttag(self, tag, attrs):
        self.parts.append(" ")

    def handle_endtag(self, tag):
        self.parts.append(" ")

    def handle_startendtag(self, tag, attrs):
        self.parts.append(" ")


def _html_to_text(fragment):
    parser = _TextExtractor()
    parser.feed(fragment)
    parser.close()
    return "".join(parser.parts)


def clean_description(raw):
    """Remove HTML tags and entities, collapse whitespace.

    The text is parsed twice because some sellers write escaped HTML
    (``&lt;span&gt;``): the first pass decodes it into a real tag, the second
    pass removes that tag (Bug 9). An HTML parser is used instead of a regex,
    so plain text such as ``I love it <3`` is kept.
    """
    if not raw:
        return ""
    text = _html_to_text(_html_to_text(raw))
    return re.sub(r"\s+", " ", text).strip()


def extract(data):
    """Keep only the fields required by the project."""
    images = data.get("images") or []
    return {
        "id": data.get("id"),
        "name": data.get("name"),
        "url_key": data.get("url_key"),
        "price": data.get("price"),
        "description": clean_description(data.get("description")),
        "images": [img.get("base_url") or img.get("large_url") for img in images
                   if img.get("base_url") or img.get("large_url")],
    }
