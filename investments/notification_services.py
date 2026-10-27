import html
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit


ALLOWED_TAGS = {
    "a", "b", "blockquote", "br", "code", "del", "div", "em", "h1", "h2",
    "h3", "h4", "hr", "i", "ins", "li", "ol", "p", "pre", "s", "span",
    "strong", "table", "tbody", "td", "tfoot", "th", "thead", "tr", "u", "ul",
}
VOID_TAGS = {"br", "hr"}
BLOCKED_TAGS = {"embed", "iframe", "math", "object", "script", "style", "svg", "template"}
GLOBAL_ATTRIBUTES = {"dir", "lang", "title"}


def _safe_href(value):
    cleaned = "".join(character for character in value.strip() if ord(character) > 31 and ord(character) != 127)
    parts = urlsplit(cleaned)
    if parts.scheme and parts.scheme.lower() not in {"http", "https", "mailto", "tel"}:
        return ""
    if not parts.scheme and cleaned.startswith("//"):
        return ""
    return cleaned


class _NotificationHTMLSanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.output = []
        self.open_tags = []
        self.blocked_stack = []

    def handle_starttag(self, tag, attrs):
        if self.blocked_stack:
            if tag in BLOCKED_TAGS:
                self.blocked_stack.append(tag)
            return
        if tag in BLOCKED_TAGS:
            self.blocked_stack.append(tag)
            return
        if tag not in ALLOWED_TAGS:
            return

        safe_attrs = []
        target_blank = False
        for name, value in attrs:
            if value is None:
                continue
            if name in GLOBAL_ATTRIBUTES:
                if name == "dir" and value not in {"ltr", "rtl", "auto"}:
                    continue
                if name == "lang" and not re.fullmatch(r"[A-Za-z0-9-]{1,35}", value):
                    continue
                safe_attrs.append((name, value))
            elif tag == "a" and name == "href":
                href = _safe_href(value)
                if href:
                    safe_attrs.append(("href", href))
            elif tag == "a" and name == "target" and value == "_blank":
                target_blank = True
            elif tag in {"td", "th"} and name in {"colspan", "rowspan"}:
                if value.isdigit() and 1 <= int(value) <= 20:
                    safe_attrs.append((name, value))
            elif tag == "ol" and name == "start" and value.lstrip("-").isdigit():
                if -1000 <= int(value) <= 1000:
                    safe_attrs.append((name, value))

        if target_blank:
            safe_attrs.append(("target", "_blank"))
            safe_attrs.append(("rel", "noopener noreferrer"))
        rendered_attrs = "".join(
            f' {name}="{html.escape(value, quote=True)}"' for name, value in safe_attrs
        )
        self.output.append(f"<{tag}{rendered_attrs}>")
        if tag not in VOID_TAGS:
            self.open_tags.append(tag)

    def handle_endtag(self, tag):
        if self.blocked_stack:
            if tag in self.blocked_stack:
                index = len(self.blocked_stack) - 1 - self.blocked_stack[::-1].index(tag)
                del self.blocked_stack[index:]
            return
        if tag not in self.open_tags:
            return
        while self.open_tags:
            opened = self.open_tags.pop()
            self.output.append(f"</{opened}>")
            if opened == tag:
                break

    def handle_data(self, data):
        if not self.blocked_stack:
            self.output.append(html.escape(data, quote=False))

    def finish(self, source):
        self.feed(source)
        self.close()
        while self.open_tags:
            self.output.append(f"</{self.open_tags.pop()}>")
        return "".join(self.output)


def sanitize_notification_html(source):
    return _NotificationHTMLSanitizer().finish(source or "")
