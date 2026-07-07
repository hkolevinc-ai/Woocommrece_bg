#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
WooCommerce BG Finder v2

Цел:
- открива публично видими WooCommerce магазини;
- проверява дали са на български;
- извлича име на сайт, фирма, ЕИК, категория, email;
- маркира хостинг държава и CDN/proxy;
- НЕ реже кандидатите твърде рано по IP, защото Cloudflare/CDN често скрива реалния хостинг.

Изход:
output/01_verified_woocommerce_bg_language.xlsx
output/02_confirmed_hosted_in_bg.xlsx
output/03_possible_bg_or_cdn.xlsx
output/99_all_checked.xlsx
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import csv
import html
import json
import os
import random
import re
import socket
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple
from urllib import robotparser
from urllib.parse import urljoin, urlparse, unquote

import pandas as pd
import requests
from bs4 import BeautifulSoup

try:
    import dns.resolver
except Exception:
    dns = None


HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; WooCommerceBGFinder/2.0; +https://example.com/bot)"
}

COMMONCRAWL_COLLINFO = "https://index.commoncrawl.org/collinfo.json"

BG_PUBLIC_SUFFIXES = {
    "bg", "com.bg", "net.bg", "org.bg", "edu.bg", "ac.bg",
    "gov.bg", "mil.bg", "inf.bg", "name.bg", "biz.bg"
}

# По-силни WooCommerce маркери. Важно: не разчитаме само на един marker.
WOOCOMMERCE_MARKERS = [
    "wp-content/plugins/woocommerce",
    "woocommerce",
    "wc-ajax",
    "wc-block",
    "wc_cart",
    "woocommerce-cart",
    "woocommerce-checkout",
    "add_to_cart_button",
    "single_add_to_cart_button",
    "data-product_id",
    "?add-to-cart=",
    "product_cat",
    "woocommerce-product-gallery",
    "wc/store/v1",
    "wc/store/cart",
    "woocommerce_price",
]

BG_LANGUAGE_MARKERS = [
    " лв", "лв.", "доставка", "поръчка", "количка", "кошница", "продукт", "продукти",
    "плащане", "наложен платеж", "общи условия", "контакти", "в наличност",
    "добави в количката", "добавяне в количката", "купи", "цена", "връщане", "замяна",
    "ддс", "еик", "работно време", "българия"
]

CONTACT_LINK_MARKERS = [
    "contact", "kontakti", "kontact", "kontakt", "контакт", "contacts",
    "za-nas", "about", "about-us", "за-нас", "obshti-usloviya",
    "общи-условия", "usloviya", "terms", "privacy", "gdpr",
    "politika", "политика", "dostavka", "delivery", "доставка",
    "plasztane", "plashtane", "плащане", "vrushtane", "връщане"
]

CDN_OR_PROXY_WORDS = [
    "cloudflare", "akamai", "fastly", "cloudfront", "amazon", "aws",
    "google", "gcore", "bunny", "sucuri", "imperva", "stackpath",
    "microsoft", "azure", "cdn", "proxy"
]

CATEGORY_KEYWORDS = {
    "Мода / дрехи / обувки": [
        "дрех", "облекло", "мода", "fashion", "рокл", "блуз", "тениск", "обув",
        "дамски", "мъжки", "детски дрехи", "чанти", "бельо", "палто", "яке", "панталон"
    ],
    "Козметика / парфюми": [
        "козмет", "парфюм", "крем", "шампоан", "грим", "beauty", "skin", "коса",
        "маникюр", "лак", "серум", "аромат", "маска", "червило"
    ],
    "Авточасти / автоаксесоари": [
        "авточасти", "авто", "bmw", "mercedes", "audi", "части", "масло", "гуми",
        "акумулатор", "фар", "броня", "ремък", "чистачки", "дискове", "накладки"
    ],
    "Електроника / техника": [
        "електроник", "телефон", "лаптоп", "компют", "таблет", "смартфон", "аксесоар",
        "кабел", "зарядно", "camera", "камера", "слушалки", "телевизор", "смарт"
    ],
    "Дом / градина / мебели": [
        "мебели", "дом", "градина", "кухня", "матрак", "спалня", "осветление",
        "интериор", "декорация", "баня", "текстил", "завеса", "килими"
    ],
    "Спорт / фитнес / outdoor": [
        "спорт", "фитнес", "колело", "велосипед", "туризъм", "къмпинг", "running",
        "run", "тренировка", "екипировка", "спортни", "йога", "риболов", "лов"
    ],
    "Храни / напитки": [
        "храна", "напитки", "био", "кафе", "чай", "шоколад", "подправки",
        "ядки", "сладки", "мед", "зехтин", "вино", "деликатеси"
    ],
    "Хранителни добавки / здраве": [
        "добавки", "протеин", "витамин", "магнезий", "колаген", "здраве",
        "supplement", "omega", "креатин", "аминокиселини", "минерали"
    ],
    "Детски стоки / играчки": [
        "детски", "играчки", "бебе", "бебешки", "количка", "ученически", "раница",
        "пъзел", "игра", "памперс", "детска", "деца"
    ],
    "Книги / канцеларски / училищни": [
        "книги", "книга", "канцелар", "офис", "училищ", "тетрад", "химикал",
        "молив", "учебник", "арт", "материали", "папка"
    ],
    "Бижута / часовници / аксесоари": [
        "бижу", "часовник", "гривна", "колие", "обеци", "пръстен", "аксесоари"
    ],
    "Домашни любимци": [
        "куче", "котка", "домашни любимци", "pet", "храна за кучета", "храна за котки", "зоомагазин"
    ],
    "Инструменти / строителство": [
        "инструмент", "строител", "винтоверт", "машини", "бормашина", "лепило",
        "боя", "ремонт", "крепеж", "електрожен"
    ],
    "Цветя / подаръци": [
        "цветя", "букет", "подарък", "подаръци", "балони", "картичка", "сувенир"
    ],
}


@dataclass
class SiteResult:
    site_name: str = ""
    domain: str = ""
    start_url: str = ""
    final_url: str = ""
    company: str = ""
    eik: str = ""
    category: str = ""
    emails: str = ""
    contact_page: str = ""
    is_woocommerce: bool = False
    woocommerce_score: int = 0
    is_online_shop: bool = False
    online_shop_score: int = 0
    is_bulgarian: bool = False
    bg_language_score: int = 0
    ip: str = ""
    hosting_country: str = ""
    hosting_org: str = ""
    hosted_in_bg: bool = False
    cdn_or_proxy: bool = False
    candidate_score: int = 0
    candidate_sources: str = ""
    status: str = ""
    notes: str = ""


class RobotsCache:
    def __init__(self) -> None:
        self.cache: Dict[str, robotparser.RobotFileParser] = {}

    def can_fetch(self, url: str, user_agent: str = HEADERS["User-Agent"]) -> bool:
        parsed = urlparse(url)
        root = f"{parsed.scheme}://{parsed.netloc}"
        if root not in self.cache:
            rp = robotparser.RobotFileParser()
            rp.set_url(urljoin(root, "/robots.txt"))
            try:
                rp.read()
            except Exception:
                return True
            self.cache[root] = rp
        try:
            return self.cache[root].can_fetch(user_agent, url)
        except Exception:
            return True


ROBOTS = RobotsCache()
IP_CACHE: Dict[str, Tuple[str, str, bool]] = {}


def safe_get(url: str, timeout: int = 15, respect_robots: bool = True) -> Optional[requests.Response]:
    if respect_robots and not ROBOTS.can_fetch(url):
        return None
    try:
        time.sleep(random.uniform(0.04, 0.18))
        r = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        if r.status_code >= 400:
            return None
        ctype = (r.headers.get("content-type") or "").lower()
        if ctype and ("text/html" not in ctype and "application/xhtml" not in ctype):
            return None
        return r
    except requests.RequestException:
        return None


def safe_get_json(url: str, timeout: int = 12, respect_robots: bool = True):
    if respect_robots and not ROBOTS.can_fetch(url):
        return None
    try:
        time.sleep(random.uniform(0.04, 0.15))
        r = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        if r.status_code >= 400:
            return None
        ctype = (r.headers.get("content-type") or "").lower()
        if "json" not in ctype and not r.text.strip().startswith(("[", "{")):
            return None
        return r.json()
    except Exception:
        return None


def clean_value(value: str) -> str:
    value = html.unescape(unquote(value or ""))
    value = re.sub(r"\s+", " ", value)
    return value.strip(" \t\r\n-–—|:;,. ")


def normalize_host(host: str) -> str:
    host = (host or "").lower().strip().strip(".")
    if host.startswith("www."):
        host = host[4:]
    return host


def registrable_domain(host: str) -> str:
    host = normalize_host(host)
    labels = host.split(".")
    if len(labels) <= 2:
        return host
    for suffix in sorted(BG_PUBLIC_SUFFIXES, key=lambda s: -len(s.split("."))):
        suff_labels = suffix.split(".")
        if labels[-len(suff_labels):] == suff_labels and len(labels) > len(suff_labels):
            return ".".join(labels[-len(suff_labels)-1:])
    return ".".join(labels[-2:])


def domain_from_url(url: str) -> str:
    parsed = urlparse(url if url.startswith(("http://", "https://")) else "https://" + url)
    return registrable_domain(parsed.hostname or "")


def homepage_candidates(domain: str) -> List[str]:
    return [
        f"https://{domain}/",
        f"https://www.{domain}/",
        f"http://{domain}/",
        f"http://www.{domain}/",
    ]


def get_latest_commoncrawl_indexes(n: int) -> List[Tuple[str, str]]:
    r = requests.get(COMMONCRAWL_COLLINFO, headers=HEADERS, timeout=30)
    r.raise_for_status()
    data = r.json()
    items = [(x.get("id"), x.get("cdx-api")) for x in data if x.get("id") and x.get("cdx-api")]
    return items[:n]


def query_commoncrawl_index(api_url: str, pattern: str, limit: int) -> Iterable[str]:
    params = {
        "url": pattern,
        "output": "json",
        "fl": "url",
        "filter": "status:200",
        "collapse": "urlkey",
        "limit": str(limit),
    }
    try:
        with requests.get(api_url, headers=HEADERS, params=params, timeout=100, stream=True) as r:
            if r.status_code != 200:
                return
            count = 0
            for line in r.iter_lines(decode_unicode=True):
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    url = obj.get("url")
                    if url:
                        yield url
                        count += 1
                        if count >= limit:
                            break
                except json.JSONDecodeError:
                    continue
    except requests.RequestException:
        return


def discover_candidates_commoncrawl(indexes: int, limit_per_pattern: int, global_discovery: bool) -> Dict[str, Dict[str, object]]:
    """
    Връща dict: domain -> {score:int, sources:set}
    v2 сортира по score, за да не взима произволни първи 100 сайта.
    """
    # pattern, score, label
    patterns: List[Tuple[str, int, str]] = [
        ("*.bg/wp-content/plugins/woocommerce/*", 10, "bg_woocommerce_plugin"),
        ("*.bg/*wc-ajax=*", 9, "bg_wc_ajax"),
        ("*.bg/*add-to-cart=*", 9, "bg_add_to_cart"),
        ("*.bg/wp-json/wc/*", 9, "bg_wc_api"),
        ("*.bg/product-category/*", 5, "bg_product_category"),
        ("*.bg/shop/*", 4, "bg_shop"),
        ("*.bg/magazin/*", 4, "bg_magazin"),
        ("*.bg/produkt/*", 4, "bg_produkt"),
        ("*.bg/product/*", 3, "bg_product"),
        ("*.bg/kolichka/*", 3, "bg_cart_bg"),
        ("*.bg/koshnica/*", 3, "bg_cart_bg2"),
        ("*.bg/cart/*", 2, "bg_cart"),
        ("*.bg/checkout/*", 2, "bg_checkout"),
    ]

    if global_discovery:
        # По-бавно и по-шумно, но намира български магазини на .com/.eu, ако Common Crawl ги върне.
        patterns.extend([
            ("*/wp-content/plugins/woocommerce/*", 6, "global_woocommerce_plugin"),
            ("*/wp-json/wc/*", 5, "global_wc_api"),
            ("*/magazin/*", 3, "global_magazin"),
            ("*/produkt/*", 3, "global_produkt"),
        ])

    found: Dict[str, Dict[str, object]] = {}
    idxs = get_latest_commoncrawl_indexes(indexes)

    for crawl_id, api_url in idxs:
        print(f"[Common Crawl] {crawl_id}")
        for pattern, weight, label in patterns:
            print(f"  pattern: {pattern}")
            local_count = 0
            for url in query_commoncrawl_index(api_url, pattern, limit_per_pattern):
                d = domain_from_url(url)
                if not d or "." not in d:
                    continue
                if d not in found:
                    found[d] = {"score": 0, "sources": set()}
                found[d]["score"] = int(found[d]["score"]) + weight
                found[d]["sources"].add(label)
                local_count += 1
            print(f"    urls: {local_count} | domains so far: {len(found)}")
    return found


def load_seed_domains(path: Optional[str]) -> Dict[str, Dict[str, object]]:
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    domains: Dict[str, Dict[str, object]] = {}
    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        d = domain_from_url(line)
        if d:
            domains[d] = {"score": 20, "sources": {"seed"}}
    return domains


def soup_from_response(r: requests.Response) -> BeautifulSoup:
    if not r.encoding:
        r.encoding = r.apparent_encoding
    return BeautifulSoup(r.text, "html.parser")


def strip_text(soup: BeautifulSoup) -> str:
    # Копие не правим за скорост; важните link тагове остават.
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    text = soup.get_text(" ", strip=True)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text[:70000]


def get_site_name(soup: BeautifulSoup, domain: str) -> str:
    og = soup.find("meta", property="og:site_name")
    if og and og.get("content"):
        return clean_value(og["content"])[:140]
    app = soup.find("meta", attrs={"name": "application-name"})
    if app and app.get("content"):
        return clean_value(app["content"])[:140]
    title = soup.find("title")
    if title and title.get_text(strip=True):
        t = clean_value(title.get_text(" ", strip=True))
        parts = [p.strip() for p in re.split(r"\s+[–—|]\s+|\s+-\s+", t) if p.strip()]
        if len(parts) >= 2:
            return clean_value(parts[-1])[:140]
        return t[:140]
    return domain


def score_woocommerce(html_text: str, visible_text: str = "") -> int:
    lower = (html_text + " " + visible_text).lower()
    score = 0
    for m in WOOCOMMERCE_MARKERS:
        if m.lower() in lower:
            score += 1
    if "wp-content/plugins/woocommerce" in lower:
        score += 6
    if "wc-ajax" in lower:
        score += 3
    if "?add-to-cart=" in lower or "add_to_cart_button" in lower or "single_add_to_cart_button" in lower:
        score += 4
    if "woocommerce-product-gallery" in lower:
        score += 3
    if "wc/store/v1" in lower:
        score += 4
    return score


def score_online_shop(text: str, html_text: str) -> int:
    lower = (text + " " + html_text).lower()
    markers = [
        "добави в количката", "добавяне в количката", "количка", "кошница", "checkout",
        "cart", "наложен платеж", "плащане", "поръчка", "цена", "лв.", " лв", "в наличност",
        "изчерпан", "sku", "категория", "product", "shop"
    ]
    score = sum(1 for m in markers if m in lower)
    if re.search(r"\d+[,.]?\d*\s*(?:лв\.?|bgn|eur|€)", lower):
        score += 3
    return score


def score_bulgarian(soup: BeautifulSoup, text: str) -> int:
    score = 0
    html_tag = soup.find("html")
    if html_tag and html_tag.get("lang") and "bg" in html_tag.get("lang", "").lower():
        score += 6
    cyrillic = len(re.findall(r"[А-Яа-я]", text))
    if cyrillic > 700:
        score += 7
    elif cyrillic > 250:
        score += 5
    elif cyrillic > 80:
        score += 3
    lower = text.lower()
    for marker in BG_LANGUAGE_MARKERS:
        if marker in lower:
            score += 1
    return score


def extract_emails(text: str, html_text: str) -> List[str]:
    combined = html.unescape(text + " " + html_text)
    mailtos = re.findall(r"mailto:([^\"'\s?<>]+)", combined, flags=re.I)
    normal = re.findall(
        r"(?<![A-Za-z0-9._%+-])([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})(?![A-Za-z0-9._%+-])",
        combined,
        flags=re.I,
    )
    deob = combined
    replacements = [
        (r"\s*\[\s*at\s*\]\s*", "@"),
        (r"\s*\(\s*at\s*\)\s*", "@"),
        (r"\s+at\s+", "@"),
        (r"\s*\[\s*dot\s*\]\s*", "."),
        (r"\s*\(\s*dot\s*\)\s*", "."),
        (r"\s+dot\s+", "."),
        (r"\s*\[\s*аt\s*\]\s*", "@"),
    ]
    for pat, repl in replacements:
        deob = re.sub(pat, repl, deob, flags=re.I)
    obfuscated = re.findall(
        r"(?<![A-Za-z0-9._%+-])([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})(?![A-Za-z0-9._%+-])",
        deob,
        flags=re.I,
    )
    emails = []
    for e in mailtos + normal + obfuscated:
        e = clean_value(e).lower()
        if not e:
            continue
        if any(bad in e for bad in ["example.com", "yourdomain", "domain.com", "sentry.io", "w.org"]):
            continue
        if e.endswith((".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif")):
            continue
        emails.append(e)
    return sorted(set(emails))


def extract_company_and_eik(text: str) -> Tuple[str, str]:
    t = clean_value(text)
    eik = ""
    eik_match = re.search(r"(?:ЕИК|Булстат|BULSTAT|ДДС|VAT)\s*[:№#]?\s*([A-ZА-Я]{0,3}\s*\d{9,13})", t, flags=re.I)
    if eik_match:
        eik = clean_value(eik_match.group(1))

    company_patterns = [
        r"([„\"“”]?[А-ЯA-Z0-9][А-Яа-яA-Za-z0-9\s\.\-&\"„“”]{2,95}[\"“”]?\s+(?:ЕООД|ООД|ЕАД|АД|ЕТ|СД|КД))",
        r"((?:ЕООД|ООД|ЕАД|АД|ЕТ)\s+[„\"“”]?[А-ЯA-Z0-9][А-Яа-яA-Za-z0-9\s\.\-&\"„“”]{2,95})",
        r"(?:Фирма|Дружество|Търговец|Продавач|Оператор|Администратор|Собственик)\s*[:\-]\s*([^,\n\r;]{3,120})",
    ]
    candidates = []
    for pat in company_patterns:
        for m in re.finditer(pat, t, flags=re.I):
            val = clean_value(m.group(1))
            if 3 <= len(val) <= 140:
                candidates.append(val)

    cleaned = []
    for c in candidates:
        c = re.sub(r"^(на|от|за)\s+", "", c, flags=re.I)
        if any(x.lower() in c.lower() for x in ["cookie", "woocommerce", "wordpress", "политика за"]):
            continue
        cleaned.append(c)
    company = cleaned[0] if cleaned else ""
    return company, eik


def infer_category(text: str, site_name: str) -> str:
    hay = (site_name + " " + text[:18000]).lower()
    scores = {}
    for cat, words in CATEGORY_KEYWORDS.items():
        score = sum(1 for w in words if w.lower() in hay)
        if score:
            scores[cat] = score
    if not scores:
        return "Неясна / друга"
    return max(scores.items(), key=lambda kv: kv[1])[0]


def extract_contact_links(base_url: str, soup: BeautifulSoup, max_links: int = 10) -> List[str]:
    links = []
    seen = set()
    base_host = normalize_host(urlparse(base_url).hostname or "")
    for a in soup.find_all("a", href=True):
        href = a.get("href") or ""
        label = (a.get_text(" ", strip=True) + " " + href).lower()
        if not any(m.lower() in label for m in CONTACT_LINK_MARKERS):
            continue
        url = urljoin(base_url, href)
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            continue
        if normalize_host(parsed.hostname or "") != base_host:
            continue
        url = parsed._replace(fragment="").geturl()
        if url not in seen:
            seen.add(url)
            links.append(url)
        if len(links) >= max_links:
            break
    return links


def resolve_ip(domain: str) -> str:
    try:
        if dns:
            answers = dns.resolver.resolve(domain, "A", lifetime=5)
            for a in answers:
                return str(a)
    except Exception:
        pass
    try:
        return socket.gethostbyname(domain)
    except Exception:
        return ""


def lookup_ipinfo(ip: str) -> Tuple[str, str, bool]:
    if not ip:
        return "", "", False
    if ip in IP_CACHE:
        return IP_CACHE[ip]

    token = os.getenv("IPINFO_TOKEN", "").strip()
    result = ("", "", False)
    try:
        if token:
            url = f"https://ipinfo.io/{ip}/json?token={token}"
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.status_code == 200:
                data = r.json()
                country = data.get("country", "")
                org = data.get("org") or data.get("asn", {}).get("name", "") or ""
                cdn = any(w in org.lower() for w in CDN_OR_PROXY_WORDS)
                result = (country, org, cdn)
                IP_CACHE[ip] = result
                return result

        url = f"http://ip-api.com/json/{ip}?fields=status,countryCode,org,as,query,hosting,proxy"
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code == 200:
            data = r.json()
            country = data.get("countryCode", "") or ""
            org = data.get("org") or data.get("as") or ""
            cdn = bool(data.get("proxy")) or any(w in org.lower() for w in CDN_OR_PROXY_WORDS)
            result = (country, org, cdn)
    except requests.RequestException:
        pass

    IP_CACHE[ip] = result
    return result


def fetch_best_homepage(domain: str, respect_robots: bool) -> Tuple[str, Optional[requests.Response]]:
    for url in homepage_candidates(domain):
        r = safe_get(url, respect_robots=respect_robots)
        if r is not None:
            return url, r
    return "", None


def check_wc_store_api(base_url: str, respect_robots: bool) -> Tuple[int, str]:
    """WooCommerce Store API често е публичен и е силен сигнал за реален Woo магазин."""
    endpoints = [
        urljoin(base_url, "/wp-json/wc/store/v1/products?per_page=1"),
        urljoin(base_url, "/wp-json/wc/store/v1"),
    ]
    for endpoint in endpoints:
        data = safe_get_json(endpoint, respect_robots=respect_robots)
        if data is None:
            continue
        if isinstance(data, list):
            return 7, endpoint
        if isinstance(data, dict) and ("routes" in data or "namespace" in data or "name" in data):
            return 5, endpoint
    return 0, ""


def analyse_domain(domain: str, meta: Dict[str, object], respect_robots: bool) -> SiteResult:
    result = SiteResult(
        domain=domain,
        start_url=f"https://{domain}/",
        candidate_score=int(meta.get("score", 0)),
        candidate_sources=", ".join(sorted(meta.get("sources", set()))),
    )

    # ВАЖНО v2: IP проверката е само обогатяване, не прескачаме сайта тук.
    ip = resolve_ip(domain)
    result.ip = ip
    country, org, cdn = lookup_ipinfo(ip)
    result.hosting_country = country
    result.hosting_org = org
    result.cdn_or_proxy = cdn
    result.hosted_in_bg = country.upper() == "BG" and not cdn

    home_url, r = fetch_best_homepage(domain, respect_robots=respect_robots)
    if r is None:
        result.status = "no_response"
        return result

    result.final_url = r.url
    soup = soup_from_response(r)
    raw_html = r.text
    visible = strip_text(soup)

    result.site_name = get_site_name(soup, domain)
    wc_score = score_woocommerce(raw_html, visible)
    shop_score = score_online_shop(visible, raw_html)
    bg_score = score_bulgarian(soup, visible)

    # Woo Store API check
    api_score, api_url = check_wc_store_api(r.url, respect_robots=respect_robots)
    wc_score += api_score

    pages_text = visible
    pages_html = raw_html
    contact_page_used = ""

    # Контактни/legal страници + вероятни магазин страници.
    contact_links = extract_contact_links(r.url, soup, max_links=10)
    guessed_pages = [
        urljoin(r.url, "/shop/"),
        urljoin(r.url, "/magazin/"),
        urljoin(r.url, "/магазин/"),
        urljoin(r.url, "/produkt/"),
        urljoin(r.url, "/product/"),
        urljoin(r.url, "/product-category/"),
        urljoin(r.url, "/cart/"),
        urljoin(r.url, "/checkout/"),
        urljoin(r.url, "/kolichka/"),
        urljoin(r.url, "/koshnica/"),
        urljoin(r.url, "/kontakti/"),
        urljoin(r.url, "/contact/"),
        urljoin(r.url, "/obshti-usloviya/"),
        urljoin(r.url, "/privacy-policy/"),
    ]

    pages_to_check: List[str] = []
    for u in contact_links + guessed_pages:
        if u not in pages_to_check:
            pages_to_check.append(u)

    for page_url in pages_to_check[:18]:
        rr = safe_get(page_url, respect_robots=respect_robots)
        if rr is None:
            continue
        ss = soup_from_response(rr)
        tt = strip_text(ss)
        pages_text += " " + tt
        pages_html += " " + rr.text
        wc_score += score_woocommerce(rr.text, tt)
        shop_score += score_online_shop(tt, rr.text)
        bg_score = max(bg_score, score_bulgarian(ss, tt))
        if not contact_page_used and any(m in page_url.lower() for m in CONTACT_LINK_MARKERS):
            contact_page_used = rr.url

    emails = extract_emails(pages_text, pages_html)
    company, eik = extract_company_and_eik(pages_text)
    category = infer_category(pages_text, result.site_name)

    result.woocommerce_score = wc_score
    result.is_woocommerce = wc_score >= 4
    result.online_shop_score = shop_score
    result.is_online_shop = shop_score >= 5
    result.bg_language_score = bg_score
    result.is_bulgarian = bg_score >= 5
    result.emails = ", ".join(emails)
    result.company = company
    result.eik = eik
    result.category = category
    result.contact_page = contact_page_used or (contact_links[0] if contact_links else "")

    if result.is_woocommerce and result.is_bulgarian and result.is_online_shop:
        result.status = "verified_woocommerce_bg_shop"
    elif result.is_woocommerce and result.is_bulgarian:
        result.status = "verified_woocommerce_bg_possible_shop"
    else:
        result.status = "filtered"
        notes = []
        if not result.is_woocommerce:
            notes.append("Not enough WooCommerce signals")
        if not result.is_online_shop:
            notes.append("Not enough online shop signals")
        if not result.is_bulgarian:
            notes.append("Not enough Bulgarian language signals")
        result.notes = "; ".join(notes)
    if api_url:
        result.notes = (result.notes + "; " if result.notes else "") + f"Woo Store API: {api_url}"
    if result.cdn_or_proxy:
        result.notes = (result.notes + "; " if result.notes else "") + "CDN/proxy may hide real hosting"
    return result


def output_columns(df: pd.DataFrame) -> pd.DataFrame:
    preferred_cols = [
        "site_name", "domain", "final_url", "company", "eik", "category", "emails",
        "contact_page", "is_woocommerce", "woocommerce_score", "is_online_shop", "online_shop_score",
        "is_bulgarian", "bg_language_score", "ip", "hosting_country", "hosting_org",
        "hosted_in_bg", "cdn_or_proxy", "candidate_score", "candidate_sources", "status", "notes"
    ]
    return df[[c for c in preferred_cols if c in df.columns]]


def write_df(df: pd.DataFrame, path_base: Path) -> None:
    df.to_excel(str(path_base) + ".xlsx", index=False)
    df.to_csv(str(path_base) + ".csv", index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL)


def save_results(results: List[SiteResult], out_dir: str) -> None:
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    rows = [asdict(r) for r in results]
    df = output_columns(pd.DataFrame(rows))

    all_checked = Path(out_dir) / "99_all_checked"
    write_df(df, all_checked)

    verified = df[
        (df["is_woocommerce"] == True) &
        (df["is_bulgarian"] == True) &
        (df["is_online_shop"] == True)
    ].copy()
    write_df(verified, Path(out_dir) / "01_verified_woocommerce_bg_language")

    confirmed_bg = verified[(verified["hosted_in_bg"] == True)].copy()
    write_df(confirmed_bg, Path(out_dir) / "02_confirmed_hosted_in_bg")

    # За lead generation е полезно: Woo + BG магазин, като не режем CDN/unknown, защото реалният origin може да е в BG.
    possible_bg_or_cdn = verified[
        (verified["hosted_in_bg"] == True) |
        (verified["cdn_or_proxy"] == True) |
        (verified["hosting_country"].fillna("") == "")
    ].copy()
    write_df(possible_bg_or_cdn, Path(out_dir) / "03_possible_bg_or_cdn")

    no_email = verified[verified["emails"].fillna("") == ""].copy()
    write_df(no_email, Path(out_dir) / "04_verified_no_email_found")

    print("\nDONE")
    print(f"Checked: {len(df)}")
    print(f"Verified WooCommerce + BG language + online shop: {len(verified)}")
    print(f"Confirmed hosted in BG: {len(confirmed_bg)}")
    print(f"Possible BG / CDN / unknown hosting: {len(possible_bg_or_cdn)}")
    print(f"Saved folder: {Path(out_dir).resolve()}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--indexes", type=int, default=6, help="Колко последни Common Crawl индекса да провери")
    p.add_argument("--limit-per-pattern", type=int, default=50000, help="Лимит URL-и на pattern за Common Crawl")
    p.add_argument("--seeds", default="seeds.txt", help="Файл с допълнителни домейни/URL-и за проверка")
    p.add_argument("--max-sites", type=int, default=0, help="0 = без лимит; полезно за тест")
    p.add_argument("--workers", type=int, default=12, help="Паралелни проверки")
    p.add_argument("--out", default="output", help="Папка за резултатите")
    p.add_argument("--global-discovery", action="store_true", help="По-бавно: търси WooCommerce следи и извън .bg")
    p.add_argument("--no-robots", action="store_true", help="Не проверява robots.txt")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    domains_meta: Dict[str, Dict[str, object]] = {}

    seed_domains = load_seed_domains(args.seeds)
    if seed_domains:
        print(f"Loaded {len(seed_domains)} seed domains from {args.seeds}")
        domains_meta.update(seed_domains)

    print("Discovering candidates from Common Crawl...")
    try:
        cc = discover_candidates_commoncrawl(args.indexes, args.limit_per_pattern, args.global_discovery)
        print(f"Common Crawl candidate domains: {len(cc)}")
        for d, meta in cc.items():
            if d not in domains_meta:
                domains_meta[d] = meta
            else:
                domains_meta[d]["score"] = int(domains_meta[d].get("score", 0)) + int(meta.get("score", 0))
                domains_meta[d]["sources"] = set(domains_meta[d].get("sources", set())) | set(meta.get("sources", set()))
    except Exception as e:
        print(f"Common Crawl discovery failed: {e}", file=sys.stderr)

    # Сортиране по кандидат score: така max-sites=100 взима най-вероятните, не първите по азбука.
    sorted_items = sorted(
        domains_meta.items(),
        key=lambda kv: (int(kv[1].get("score", 0)), kv[0].endswith(".bg")),
        reverse=True,
    )

    if args.max_sites and args.max_sites > 0:
        sorted_items = sorted_items[:args.max_sites]

    print(f"Total domains to verify: {len(sorted_items)}")
    if sorted_items:
        Path(args.out).mkdir(parents=True, exist_ok=True)
        pd.DataFrame([
            {"domain": d, "candidate_score": m.get("score", 0), "candidate_sources": ", ".join(sorted(m.get("sources", set())))}
            for d, m in sorted_items
        ]).to_csv(Path(args.out) / "00_candidates.csv", index=False, encoding="utf-8-sig")

    results: List[SiteResult] = []
    respect_robots = not args.no_robots

    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        future_map = {ex.submit(analyse_domain, d, meta, respect_robots): d for d, meta in sorted_items}
        done_count = 0
        for fut in cf.as_completed(future_map):
            d = future_map[fut]
            done_count += 1
            try:
                res = fut.result()
            except Exception as e:
                res = SiteResult(domain=d, status="error", notes=str(e))
            results.append(res)
            if done_count % 25 == 0 or done_count == len(sorted_items):
                verified = sum(1 for r in results if r.is_woocommerce and r.is_bulgarian and r.is_online_shop)
                hosted = sum(1 for r in results if r.is_woocommerce and r.is_bulgarian and r.is_online_shop and r.hosted_in_bg)
                print(f"Checked {done_count}/{len(sorted_items)} | verified: {verified} | confirmed hosted BG: {hosted}")

    save_results(results, args.out)


if __name__ == "__main__":
    main()
