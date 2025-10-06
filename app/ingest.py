from __future__ import annotations
import asyncio
import hashlib
from datetime import datetime
from typing import Dict, List, Optional

import feedparser
import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session
from rapidfuzz import fuzz

from .config import DEFAULT_SOURCES
from .models import Article
from .summarize import summarize


def _norm_text(x: Optional[str]) -> str:
    return (x or "").strip()


def _normalize_url(url: Optional[str]) -> str:
    """Normalize URL for deduplication:
    - strip fragment (after #)
    - remove common tracking query params (utm_*, fbclid, gclid, yclid, ref, referrer)
    - collapse duplicate slashes in path
    - strip trailing slash except for root
    """
    from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

    if not url:
        return ""
    try:
        sp = urlsplit(url)
        # Drop fragment
        fragless = sp._replace(fragment="")
        # Filter query
        drop_prefixes = ("utm_",)
        drop_exact = {"fbclid", "gclid", "yclid", "ref", "referrer"}
        q = []
        for k, v in parse_qsl(fragless.query, keep_blank_values=True):
            kl = (k or "").lower()
            if kl in drop_exact or any(kl.startswith(p) for p in drop_prefixes):
                continue
            q.append((k, v))
        query = urlencode(q, doseq=True)
        # Normalize path (collapse //) and strip trailing slash (except root)
        path = "/" + "/".join([p for p in (fragless.path or "/").split("/") if p != ""]) if fragless.path else "/"
        if path != "/" and path.endswith("/"):
            path = path.rstrip("/")
        norm = fragless._replace(query=query, path=path)
        return urlunsplit(norm)
    except Exception:
        return url.strip()


def _first_paragraph(html_or_text: str) -> str:
    if not html_or_text:
        return ""
    soup = BeautifulSoup(html_or_text, "html.parser")
    # Prefer meta description
    meta = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
    if meta and meta.get("content"):
        return meta.get("content").strip()
    # Else first paragraph or text
    p = soup.find("p")
    if p and p.get_text(strip=True):
        return p.get_text(strip=True)
    # fallback to text
    text = soup.get_text(" ", strip=True)
    return text[:600]


def _make_dedup_key(title: str, url: str) -> str:
    base = (title or "") + "|" + (url or "")
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:32]


def _image_from_entry(entry) -> Optional[str]:
    # Try common RSS media fields
    try:
        media = getattr(entry, 'media_content', None) or getattr(entry, 'media_thumbnail', None)
        if media:
            if isinstance(media, list) and media:
                url = media[0].get('url')
                if url:
                    return url
            elif isinstance(media, dict):
                url = media.get('url')
                if url:
                    return url
    except Exception:
        pass
    # Enclosures
    try:
        for link in getattr(entry, 'links', []) or []:
            if link.get('rel') == 'enclosure' and link.get('type', '').startswith('image/'):
                return link.get('href')
    except Exception:
        pass
    return None


def _image_from_html(html: str) -> Optional[str]:
    try:
        soup = BeautifulSoup(html, "html.parser")
        for prop in [
            {"property": "og:image"},
            {"name": "twitter:image"},
            {"property": "og:image:url"},
        ]:
            meta = soup.find("meta", attrs=prop)
            if meta and meta.get("content"):
                return meta.get("content").strip()
    except Exception:
        pass
    return None


def _is_near_duplicate(db: Session, title: str, snippet: str, threshold: int = 88, recent_limit: int = 300) -> bool:
    """Check similarity against recent articles using rapidfuzz token_set_ratio.
    Returns True if a near-duplicate is found above threshold.
    """
    base_text = (title or "").strip()
    if snippet:
        base_text = (base_text + " " + snippet).strip()
    if not base_text:
        return False
    candidates = (
        db.query(Article.title, Article.snippet)
        .order_by(Article.id.desc())
        .limit(recent_limit)
        .all()
    )
    for ct, cs in candidates:
        cand = (ct or "")
        if cs:
            cand = (cand + " " + cs)
        if not cand:
            continue
        score = fuzz.token_set_ratio(base_text, cand)
        if score >= threshold:
            return True
    return False


async def fetch_and_store(
    db: Session,
    selected_source_keys: Optional[List[str]] = None,
    limit_per_source: int = 20,
    extra_rss: Optional[List[str]] = None,
) -> Dict[str, int]:
    """Fetch latest items from configured RSS sources and store with summaries.
    Returns stats per source.
    """
    stats: Dict[str, int] = {}
    # Simple per-run cache for fetched article pages
    page_cache: Dict[str, str] = {}
    http = httpx.AsyncClient(
        timeout=httpx.Timeout(15.0, connect=10.0, read=15.0),
        headers={
            "User-Agent": "NewsBriefBot/1.0 (+https://newsbrief.local)"
        },
    )
    try:
        # Build iterable of sources: predefined + extra RSS provided by user
        predefined = list(DEFAULT_SOURCES.items())
        extra_items = []
        if extra_rss:
            # create pseudo keys for extra sources
            for i, url in enumerate(extra_rss):
                if not url:
                    continue
                extra_items.append((f"user_rss_{i}", {"title": "Пользовательский RSS", "type": "rss", "url": url, "enabled": True}))

        for key, cfg in predefined + extra_items:
            is_user_extra = key.startswith("user_rss_")
            # Apply selection filter only to predefined sources; always allow user-provided ones
            if (selected_source_keys and key not in selected_source_keys) and not is_user_extra:
                continue
            if cfg.get("type") != "rss":
                continue
            url = cfg.get("url") or ""
            if not url:
                continue

            parsed = feedparser.parse(url)
            added = 0
            for entry in parsed.entries[:limit_per_source]:
                title = _norm_text(getattr(entry, "title", ""))
                link_raw = _norm_text(getattr(entry, "link", ""))
                link = _normalize_url(link_raw)
                published = None
                if getattr(entry, "published_parsed", None):
                    published = datetime(*entry.published_parsed[:6])

                # Try to get a snippet
                snippet = _norm_text(getattr(entry, "summary", "") or getattr(entry, "description", ""))
                # sanitize to plain text if HTML provided
                if snippet:
                    snippet = _first_paragraph(snippet)
                image_url = _image_from_entry(entry)
                if not snippet:
                    # Fetch page and extract first paragraph/meta, with retry and cache
                    try:
                        text = None
                        cache_key = link or link_raw
                        if cache_key in page_cache:
                            text = page_cache[cache_key]
                        else:
                            for attempt in range(3):
                                try:
                                    r = await http.get(link or link_raw)
                                    if r.status_code == 200 and r.text:
                                        text = r.text
                                        page_cache[cache_key] = text
                                        break
                                except Exception:
                                    pass
                                await asyncio.sleep(0.5 * (2 ** attempt))
                        if text:
                            snippet = _first_paragraph(text)
                            if not image_url:
                                image_url = _image_from_html(text)
                    except Exception:
                        pass

                dedup_key = _make_dedup_key(title, link)

                # Check duplicates by URL or dedup_key
                exists = db.query(Article).filter((Article.url == link) | (Article.dedup_key == dedup_key)).first()
                if exists:
                    continue

                # Near-duplicate check using fuzzy similarity on title+snippet
                if _is_near_duplicate(db, title, snippet):
                    continue

                summary = summarize(snippet or title)

                art = Article(
                    title=title or "(без заголовка)",
                    url=link,
                    source_key=key,
                    source_title=cfg.get("title", key),
                    snippet=snippet,
                    summary=summary,
                    image_url=image_url,
                    published_at=published,
                    dedup_key=dedup_key,
                )
                db.add(art)
                added += 1

            if added:
                db.commit()
            stats[key] = added
    finally:
        await http.aclose()
    return stats
