import re
import unicodedata
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

_TRACKING = {
    # UTM 계열
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    # 광고·클릭 추적
    "fbclid", "gclid", "yclid", "dclid", "wbraid", "gbraid",
    # 메일·마케팅 자동화
    "mc_cid", "mc_eid", "_hsenc", "_hsmi", "hs_email", "hs_automation",
    # 소셜·피드 추적
    "ref", "ref_src", "ref_url", "referer",
    "source", "s",           # 많은 블로그/뉴스가 소스 트래킹에 사용
    "campaign", "medium",
    # 광고 플랫폼 고유 ID
    "igshid", "igsh",        # Instagram
    "twclid",                # Twitter
    "msclkid",               # Microsoft Ads
    "li_fat_id",             # LinkedIn
    # 기타 범용 트래킹
    "tracking_id", "track", "trk",
    "share", "shared",
    "pk_campaign", "pk_kwd",
    "cmpid", "affiliate",
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
    # fragment(#...) 제거 — 동일 기사가 #anchor 차이로 다른 해시가 되는 것 방지
    return urlunsplit((s.scheme.lower(), s.netloc.lower(), path, urlencode(q, doseq=True), ""))


def normalize_title(t: str) -> str:
    if not t:
        return ""
    t = unicodedata.normalize("NFKC", t).lower()
    t = _PUNCT.sub(" ", t)
    t = _WS.sub(" ", t).strip()
    return t
