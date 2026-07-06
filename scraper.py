#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
WooCommerce BG Finder
Открива публично видими WooCommerce сайтове, проверява дали са на български,
дали IP/хостингът е в България, и извлича име на сайт, фирма, категория и email.

Основен източник за кандидати: Common Crawl CDX Index.
Допълнително може да подадеш seeds.txt с URL-и/домейни за проверка.

ВАЖНО:
- "Всички" сайтове не може да се гарантира, защото CDN/Cloudflare и robots.txt могат да скрият произхода.
- Използвай резултатите законно и внимателно. Не изпращай масов spam.
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
from urllib.parse import quote, urljoin, urlparse, unquote
from urllib import robotparser

import pandas as pd
import requests
from bs4 import BeautifulSoup

try:
    import dns.resolver
except Exception:
    dns = None


HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; WooCommerceBGFinder/1.0; +https://example.com/bot)"
}

COMMONCRAWL_COLLINFO = "https://index.commoncrawl.org/collinfo.json"

BG_PUBLIC_SUFFIXES = {
    "bg", "com.bg", "net.bg", "org.bg", "edu.bg", "ac.bg",
    "gov.bg", "mil.bg", "inf.bg", "name.bg", "biz.bg"
}

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
    "/cart/",
    "/checkout/",
]

BG_LANGUAGE_MARKERS = [
    " лв", "лв.", "доставка", "поръчка", "количка", "продукт", "продукти",
    "плащане", "наложен платеж", "общи условия", "контакти", "в наличност",
    "добави в количката", "купи", "цена", "връщане", "замяна"
]

CONTACT_LINK_MARKERS = [
    "contact", "kontakti", "kontact", "kontakt", "контакт", "contacts",
    "za-nas", "about", "about-us", "за-нас", "obshti-usloviya",
    "общи-условия", "usloviya", "terms", "privacy", "gdpr",
    "politika", "политика", "dostavka", "delivery", "доставка"
]

CDN_OR_PROXY_WORDS = [
    "cloudflare", "akamai", "fastly", "cloudfront", "amazon", "aws",
    "google", "gcore", "bunny", "sucuri", "imperva", "stackpath",
    "microsoft", "azure", "ovh", "hetzner"
]

CATEGORY_KEYWORDS = {
    "Мода / дрехи / обувки": [
        "дрех", "облекло", "мода", "fashion", "рокл", "блуз", "тениск", "обув",
        "дамски", "мъжки", "детски дрехи", "чанти", "бельо"
    ],
    "Козметика / парфюми": [
        "козмет", "парфюм", "крем", "шампоан", "грим", "beauty", "skin", "коса",
        "маникюр", "лак", "серум"
    ],
    "Авточасти / автоаксесоари": [
        "авточасти", "авто", "bmw", "mercedes", "audi", "части", "масло", "гуми",
        "акумулатор", "фар", "броня", "ремък"
    ],
    "Електроника / техника": [
        "електроник", "телефон", "лаптоп", "компют", "таблет", "смартфон", "аксесоар",
        "кабел", "зарядно", "camera", "камера"
    ],
    "Дом / градина / мебели": [
        "мебели", "дом", "градина", "кухня", "матрак", "спалня", "осветление",
        "интериор", "декорация", "баня"
    ],
    "Спорт / фитнес / outdoor": [
        "спорт", "фитнес", "колело", "велосипед", "туризъм", "къмпинг", "running",
        "run", "тренировка", "екипировка"
    ],
    "Храни / напитки": [
        "храна", "напитки", "био", "кафе", "чай", "шоколад", "подправки",
        "ядки", "сладки", "вино"
    ],
    "Хранителни добавки / здраве": [
        "добавки", "протеин", "витамин", "магнезий", "колаген", "здраве",
        "supplement", "omega", "креатин"
    ],
    "Детски стоки / играчки": [
        "детски", "играчки", "бебе", "бебешки", "количка", "ученически", "раница",
        "пъзел", "игра"
    ],
    "Книги / канцеларски / училищни": [
        "книги", "книга", "канцелар", "офис", "училищ", "тетрад", "химикал",
        "молив", "учебник"
    ],
    "Бижута / часовници / аксесоари": [
        "бижу", "часовник", "гривна", "колие", "обеци", "пръстен", "аксесоари"
    ],
    "Домашни любимци": [
        "куче", "котка", "домашни любимци", "pet", "храна за кучета", "храна за котки"
    ],
    "Инструменти / строителство": [
        "инструмент", "строител", "винтоверт", "машини", "бормашина", "лепило",
        "боя", "ремонт"
    ],
    "Цветя / подаръци": [
        "цветя", "букет", "подарък", "подаръци", "балони", "картичка"
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
    is_bulgarian: bool = False
    bg_language_score: int = 0
    ip: str = ""
    hosting_country: str = ""
    hosting_org: str = ""
    hosted_in_bg: bool = False
    cdn_or_proxy: bool = False
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
                # Ако robots.txt не може да се прочете, не блокираме проверката.
                return True
            self.cache[root] = rp
        try:
            return self.cache[root].can_fetch(user_agent, url)
        except Exception:
            return True


ROBOTS = RobotsCache()


def safe_get(url: str, timeout: int = 15, respect_robots: bool = True) -> Optional[requests.Response]:
    if respect_robots and not ROBOTS.can_fetch(url):
        return None
    try:
        time.sleep(random.uniform(0.05, 0.25))
        r = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        if r.status_code >= 400:
            return None
        ctype = (r.headers.get("content-type") or "").lower()
        if "text/html" not in ctype and "application/xhtml" not in ctype and ctype:
            return None
        return r
    except requests.RequestException:
        return None


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
    # Обикновено са подредени от най-нов към по-стар, но сортираме за сигурност.
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
        with requests.get(api_url, headers=HEADERS, params=params, timeout=90, stream=True) as r:
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


def discover_candidates_commoncrawl(indexes: int, limit_per_pattern: int) -> Set[str]:
    """
    Намира .bg домейни, при които Common Crawl е виждал WooCommerce файлове/URL-и.
    Това е по-чисто от скрейпване на Google/Bing.
    """
    patterns = [
        "*.bg/wp-content/plugins/woocommerce/*",
        "*.bg/wp-content/uploads/woocommerce_uploads/*",
        "*.bg/*wc-ajax=*",
        "*.bg/*add-to-cart=*",
        "*.bg/product/*",
        "*.bg/product-category/*",
        "*.bg/shop/*",
        "*.bg/magazin/*",
        "*.bg/produkt/*",
    ]

    found: Set[str] = set()
    idxs = get_latest_commoncrawl_indexes(indexes)

    for crawl_id, api_url in idxs:
        print(f"[Common Crawl] {crawl_id}")
        for pattern in patterns:
            print(f"  pattern: {pattern}")
            for url in query_commoncrawl_index(api_url, pattern, limit_per_pattern):
                d = domain_from_url(url)
                if d and "." in d:
                    found.add(d)
            print(f"    found so far: {len(found)} domains")
    return found


def load_seed_domains(path: Optional[str]) -> Set[str]:
    if not path:
        return set()
    p = Path(path)
    if not p.exists():
        return set()
    domains = set()
    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        domains.add(domain_from_url(line))
    return {d for d in domains if d}


def strip_text(soup: BeautifulSoup) -> str:
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    text = soup.get_text(" ", strip=True)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text[:50000]


def soup_from_response(r: requests.Response) -> BeautifulSoup:
    if not r.encoding:
        r.encoding = r.apparent_encoding
    return BeautifulSoup(r.text, "html.parser")


def get_site_name(soup: BeautifulSoup, domain: str) -> str:
    og = soup.find("meta", property="og:site_name")
    if og and og.get("content"):
        return clean_value(og["content"])
    title = soup.find("title")
    if title and title.get_text(strip=True):
        t = title.get_text(" ", strip=True)
        # Често title е "Page - Site"; взимаме по-смислената част.
        parts = [p.strip() for p in re.split(r"\s+[–—|-]\s+", t) if p.strip()]
        if len(parts) >= 2:
            return clean_value(parts[-1])[:120]
        return clean_value(t)[:120]
    return domain


def clean_value(value: str) -> str:
    value = html.unescape(unquote(value or ""))
    value = re.sub(r"\s+", " ", value)
    return value.strip(" \t\r\n-–—|:;,. ")


def score_woocommerce(html_text: str, visible_text: str = "") -> int:
    lower = (html_text + " " + visible_text).lower()
    score = 0
    for m in WOOCOMMERCE_MARKERS:
        if m.lower() in lower:
            score += 1
    # По-силни сигнали
    if "wp-content/plugins/woocommerce" in lower:
        score += 3
    if "single_add_to_cart_button" in lower or "add_to_cart_button" in lower:
        score += 2
    if "woocommerce-product-gallery" in lower:
        score += 2
    return score


def score_bulgarian(soup: BeautifulSoup, text: str) -> int:
    score = 0
    html_tag = soup.find("html")
    if html_tag and html_tag.get("lang") and "bg" in html_tag.get("lang", "").lower():
        score += 5
    cyrillic = len(re.findall(r"[А-Яа-я]", text))
    if cyrillic > 250:
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

    # mailto:
    mailtos = re.findall(r"mailto:([^\"'\s?<>]+)", combined, flags=re.I)

    # стандартен email regex
    normal = re.findall(
        r"(?<![A-Za-z0-9._%+-])([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})(?![A-Za-z0-9._%+-])",
        combined,
        flags=re.I,
    )

    # леки обфускации: name [at] domain [dot] bg
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
        if any(bad in e for bad in ["example.com", "yourdomain", "domain.com", "sentry.io"]):
            continue
        if e.endswith((".png", ".jpg", ".jpeg", ".webp", ".svg")):
            continue
        emails.append(e)
    return sorted(set(emails))


def extract_company_and_eik(text: str) -> Tuple[str, str]:
    t = clean_value(text)

    eik = ""
    eik_match = re.search(r"(?:ЕИК|Булстат|BULSTAT|VAT|ДДС)\s*[:№#]?\s*([A-ZА-Я]{0,3}\s*\d{9,13})", t, flags=re.I)
    if eik_match:
        eik = clean_value(eik_match.group(1))

    company_patterns = [
        r"([„\"“”]?[А-ЯA-Z0-9][А-Яа-яA-Za-z0-9\s\.\-&\"„“”]{2,90}[\"“”]?\s+(?:ЕООД|ООД|ЕАД|АД|ЕТ|СД|КД))",
        r"(?:Фирма|Дружество|Търговец|Продавач|Оператор|Администратор|Собственик)\s*[:\-]\s*([^,\n\r;]{3,110})",
    ]

    candidates = []
    for pat in company_patterns:
        for m in re.finditer(pat, t, flags=re.I):
            val = clean_value(m.group(1))
            if 3 <= len(val) <= 130:
                candidates.append(val)

    # Изчистване на очевидни грешки.
    cleaned = []
    for c in candidates:
        c = re.sub(r"^(на|от|за)\s+", "", c, flags=re.I)
        if any(x.lower() in c.lower() for x in ["cookie", "woocommerce", "wordpress"]):
            continue
        cleaned.append(c)

    company = cleaned[0] if cleaned else ""
    return company, eik


def infer_category(text: str, site_name: str) -> str:
    hay = (site_name + " " + text[:12000]).lower()
    scores = {}
    for cat, words in CATEGORY_KEYWORDS.items():
        score = sum(1 for w in words if w.lower() in hay)
        if score:
            scores[cat] = score
    if not scores:
        return "Неясна / друга"
    return max(scores.items(), key=lambda kv: kv[1])[0]


def extract_contact_links(base_url: str, soup: BeautifulSoup, max_links: int = 8) -> List[str]:
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
    """
    Връща country_code, org/asn и дали прилича на CDN/Proxy.
    IPINFO_TOKEN може да се зададе в GitHub Secrets за по-стабилни резултати.
    Без token ползва ip-api.com като fallback.
    """
    if not ip:
        return "", "", False

    token = os.getenv("IPINFO_TOKEN", "").strip()
    try:
        if token:
            url = f"https://ipinfo.io/{ip}/json?token={token}"
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.status_code == 200:
                data = r.json()
                country = data.get("country", "")
                org = data.get("org") or data.get("asn", {}).get("name", "") or ""
                cdn = any(w in org.lower() for w in CDN_OR_PROXY_WORDS)
                return country, org, cdn

        # fallback без API key; има rate limits, затова кеширането е важно.
        url = f"http://ip-api.com/json/{ip}?fields=status,countryCode,org,as,query,hosting,proxy"
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code == 200:
            data = r.json()
            country = data.get("countryCode", "")
            org = data.get("org") or data.get("as") or ""
            cdn = bool(data.get("proxy")) or any(w in org.lower() for w in CDN_OR_PROXY_WORDS)
            return country, org, cdn
    except requests.RequestException:
        return "", "", False

    return "", "", False


def fetch_best_homepage(domain: str, respect_robots: bool) -> Tuple[str, Optional[requests.Response]]:
    for url in homepage_candidates(domain):
        r = safe_get(url, respect_robots=respect_robots)
        if r is not None:
            return url, r
    return "", None


def analyse_domain(domain: str, require_hosted_bg: bool, respect_robots: bool) -> SiteResult:
    result = SiteResult(domain=domain, start_url=f"https://{domain}/")

    ip = resolve_ip(domain)
    result.ip = ip
    country, org, cdn = lookup_ipinfo(ip)
    result.hosting_country = country
    result.hosting_org = org
    result.cdn_or_proxy = cdn
    result.hosted_in_bg = country.upper() == "BG" and not cdn

    if require_hosted_bg and not result.hosted_in_bg:
        result.status = "skipped_not_hosted_bg"
        if cdn:
            result.notes = "CDN/proxy hides origin; cannot confirm Bulgarian hosting"
        return result

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
    bg_score = score_bulgarian(soup, visible)

    pages_text = visible
    pages_html = raw_html
    contact_page_used = ""

    # Ако homepage не е достатъчен, проверяваме shop/contact/legal страници.
    contact_links = extract_contact_links(r.url, soup, max_links=8)

    # Добавяме вероятни shop/cart страници.
    guessed_pages = [
        urljoin(r.url, "/shop/"),
        urljoin(r.url, "/magazin/"),
        urljoin(r.url, "/produkt/"),
        urljoin(r.url, "/product/"),
        urljoin(r.url, "/cart/"),
        urljoin(r.url, "/checkout/"),
        urljoin(r.url, "/kolichka/"),
        urljoin(r.url, "/koshnica/"),
    ]

    pages_to_check = []
    for u in contact_links + guessed_pages:
        if u not in pages_to_check:
            pages_to_check.append(u)

    for page_url in pages_to_check[:14]:
        rr = safe_get(page_url, respect_robots=respect_robots)
        if rr is None:
            continue
        ss = soup_from_response(rr)
        tt = strip_text(ss)
        pages_text += " " + tt
        pages_html += " " + rr.text
        wc_score += score_woocommerce(rr.text, tt)
        bg_score = max(bg_score, score_bulgarian(ss, tt))
        if not contact_page_used and any(m in page_url.lower() for m in CONTACT_LINK_MARKERS):
            contact_page_used = rr.url

    emails = extract_emails(pages_text, pages_html)
    company, eik = extract_company_and_eik(pages_text)
    category = infer_category(pages_text, result.site_name)

    result.woocommerce_score = wc_score
    result.is_woocommerce = wc_score >= 3
    result.bg_language_score = bg_score
    result.is_bulgarian = bg_score >= 5
    result.emails = ", ".join(emails)
    result.company = company
    result.eik = eik
    result.category = category
    result.contact_page = contact_page_used or (contact_links[0] if contact_links else "")
    result.status = "ok" if (result.is_woocommerce and result.is_bulgarian) else "filtered"
    if not result.is_woocommerce:
        result.notes += "Not enough WooCommerce signals. "
    if not result.is_bulgarian:
        result.notes += "Not enough Bulgarian language signals. "
    return result


def save_results(results: List[SiteResult], out_dir: str, require_hosted_bg: bool) -> None:
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    rows = [asdict(r) for r in results]
    df = pd.DataFrame(rows)

    preferred_cols = [
        "site_name", "domain", "final_url", "company", "eik", "category", "emails",
        "contact_page", "is_woocommerce", "woocommerce_score", "is_bulgarian",
        "bg_language_score", "ip", "hosting_country", "hosting_org", "hosted_in_bg",
        "cdn_or_proxy", "status", "notes"
    ]
    df = df[[c for c in preferred_cols if c in df.columns]]

    all_xlsx = Path(out_dir) / "woocommerce_bg_all_checked.xlsx"
    all_csv = Path(out_dir) / "woocommerce_bg_all_checked.csv"

    df.to_excel(all_xlsx, index=False)
    df.to_csv(all_csv, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL)

    final = df[
        (df["is_woocommerce"] == True) &
        (df["is_bulgarian"] == True) &
        (df["hosted_in_bg"] == True)
    ].copy()

    final_xlsx = Path(out_dir) / "woocommerce_bg_final_hosted_bg.xlsx"
    final_csv = Path(out_dir) / "woocommerce_bg_final_hosted_bg.csv"
    final.to_excel(final_xlsx, index=False)
    final.to_csv(final_csv, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL)

    print("\nDONE")
    print(f"Checked: {len(df)}")
    print(f"Final WooCommerce + BG language + hosted BG: {len(final)}")
    print(f"Saved: {all_xlsx}")
    print(f"Saved: {final_xlsx}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--indexes", type=int, default=3, help="Колко последни Common Crawl индекса да провери")
    p.add_argument("--limit-per-pattern", type=int, default=20000, help="Лимит URL-и на pattern за Common Crawl")
    p.add_argument("--seeds", default="seeds.txt", help="Файл с допълнителни домейни/URL-и за проверка")
    p.add_argument("--max-sites", type=int, default=0, help="0 = без лимит; полезно за тест")
    p.add_argument("--workers", type=int, default=10, help="Паралелни проверки")
    p.add_argument("--out", default="output", help="Папка за резултатите")
    p.add_argument("--require-hosted-bg", action="store_true", help="Прескача сайтове, чийто IP не е в BG")
    p.add_argument("--no-robots", action="store_true", help="Не проверява robots.txt")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    domains = set()
    seed_domains = load_seed_domains(args.seeds)
    if seed_domains:
        print(f"Loaded {len(seed_domains)} seed domains from {args.seeds}")
        domains |= seed_domains

    print("Discovering candidates from Common Crawl...")
    try:
        cc_domains = discover_candidates_commoncrawl(args.indexes, args.limit_per_pattern)
        print(f"Common Crawl candidates: {len(cc_domains)}")
        domains |= cc_domains
    except Exception as e:
        print(f"Common Crawl discovery failed: {e}", file=sys.stderr)

    domains = sorted(d for d in domains if d and "." in d)

    if args.max_sites and args.max_sites > 0:
        domains = domains[:args.max_sites]

    print(f"Total domains to verify: {len(domains)}")

    results: List[SiteResult] = []
    respect_robots = not args.no_robots

    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        future_map = {
            ex.submit(analyse_domain, d, args.require_hosted_bg, respect_robots): d
            for d in domains
        }
        done_count = 0
        for fut in cf.as_completed(future_map):
            d = future_map[fut]
            done_count += 1
            try:
                res = fut.result()
            except Exception as e:
                res = SiteResult(domain=d, status="error", notes=str(e))
            results.append(res)

            if done_count % 25 == 0:
                good = sum(
                    1 for r in results
                    if r.is_woocommerce and r.is_bulgarian and r.hosted_in_bg
                )
                print(f"Checked {done_count}/{len(domains)} | final good: {good}")

    save_results(results, args.out, args.require_hosted_bg)


if __name__ == "__main__":
    main()
