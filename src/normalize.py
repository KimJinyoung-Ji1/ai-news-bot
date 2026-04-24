import re
import unicodedata
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

_TRACKING = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "yclid", "mc_cid", "mc_eid", "_hsenc", "_hsmi",
    "ref", "ref_src",
}
_PUNCT = re.compile(r"[\u2010-\u2015\-:;,.·!?\"'`()\[\]{}]+")
_WS = re.compile(r"\s+")


def normalize_url(u: str) -> str:
    if not u:
        return ""
    s = urlsplit(u.strip())
    q = [
        (k, v)
        for k, v in parse_qsl(s.query, keep_blank_values=False)
        if k.lower() not in _TRACKING
    ]
    path = s.path.rstrip("/") or "/"
    return urlunsplit((s.scheme.lower(), s.netloc.lower(), path, urlencode(q, doseq=True), ""))


def normalize_title(t: str) -> str:
    if not t:
        return ""
    t = unicodedata.normalize("NFKC", t).lower()
    t = _PUNCT.sub(" ", t)
    t = _WS.sub(" ", t).strip()
    return t
