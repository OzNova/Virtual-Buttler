"""JARVIS — macOS AI Assistant Backend.

Ultra-modern Flask REST backend with a typo-tolerant natural-language
intent engine and native macOS system integration.

Endpoint:
    POST /api/command   {"command": "text"}
    -> {"status": "success", "message": "JARVIS response text"}

Caching is fully disabled via after_request so the UI always reflects the
latest template/markup during development.
"""

import os
import re
import json
import html
import time
import random
import datetime
import difflib
import subprocess
import urllib.parse
import webbrowser
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except Exception:
    pass

from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# TTS voice used by the macOS `say` command.
TTS_VOICE = os.getenv("TTS_VOICE", "Daniel")

# Frontend-controlled TTS mute. When True, speak() skips the `say` command
# entirely (the UI handles its own visual waveform cues).
VOICE_MUTED = {"muted": False}

# Auto-reload templates from disk on every request during development.
app.config["TEMPLATES_AUTO_RELOAD"] = True


# ---------------------------------------------------------------------------
# Hybrid Brain — tier 1: Local Ollama (primary conversational layer)
# ---------------------------------------------------------------------------

# Local Ollama endpoint + model. Defaults to llama3.2:1b but gracefully
# falls back to whichever model the running instance actually has.
OLLAMA_BASE = os.getenv("OLLAMA_BASE", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:1b")
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "60"))

OLLAMA_SYSTEM_PROMPT = (
    "You are JARVIS, an ultra-smart, sleek macOS assistant built by OzNova. "
    "Keep responses concise, direct, natural, and under 3 sentences. "
    "Carry forward the user's open context (product brand, color, platform, "
    "task) from the conversation history below; never ask a second time for "
    "details the user already gave."
)

# Classes of prompt that obviously need live/web knowledge; the tiny local
# model is weak at these, so they skip straight to the web-capable tier.
_OLLAMA_WEB_CONTEXT_HINTS = (
    "news", "headline", "breaking", "latest", "weather", "forecast", "today",
    "current", "price", "stock", "exchange rate", "who ", "who is", "what is",
    "where is", "who are", "search the web", "look up", "on the web",
    "on the internet",
)

_OLLAMA_MODEL_CACHE = {"ts": 0.0, "model": None}


def _ollama_model():
    """Refresh every 60s: prefer OLLAMA_MODEL, else use whatever Ol"
    "lama reports. Returns None handle-free when nothing is reachable."""
    now = time.time()
    if now - _OLLAMA_MODEL_CACHE["ts"] < 60 and _OLLAMA_MODEL_CACHE["model"]:
        return _OLLAMA_MODEL_CACHE["model"]
    model = OLLAMA_MODEL
    try:
        req = urllib.request.Request(
            f"{OLLAMA_BASE}/api/tags",
            headers={"User-Agent": "Mozilla/5.0 JARVIS/1.0"},
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        names = [m.get("name", "") for m in data.get("models", [])]
        if names:
            model = OLLAMA_MODEL if OLLAMA_MODEL in names else names[0]
    except Exception:
        pass  # offline — the /api/generate call will surface the failure fast
    _OLLAMA_MODEL_CACHE.update(ts=now, model=model)
    return model or OLLAMA_MODEL


# Short in-memory chat memory so JARVIS keeps user parameters (brand, color,
# platform, task) across turns instead of re-asking what they were looking for.
CONVO_HISTORY_MAX = 6
CONVO_HISTORY = []  # list of ("user" | "jarvis", text) pairs, oldest first


def _remember(user_turn, jarvis_turn):
    """Append a (user, JARVIS) turn-pair to the rolling conversation memory."""
    if user_turn:
        CONVO_HISTORY.append(("user", user_turn))
    if jarvis_turn:
        CONVO_HISTORY.append(("jarvis", jarvis_turn))
    while len(CONVO_HISTORY) > CONVO_HISTORY_MAX * 2:
        CONVO_HISTORY.pop(0)


def _build_ollama_prompt(text):
    """Assemble the Ollama prompt from rolling history + the current turn."""
    turns = []
    for role, msg in CONVO_HISTORY[-CONVO_HISTORY_MAX * 2:]:
        turns.append(f"{'User' if role == 'user' else 'JARVIS'}: {msg}")
    turns.append(f"User: {text}")
    turns.append("JARVIS:")
    return "\n".join(turns)


def _ollama_chat(text):
    """Ask the local Ollama instance for a natural conversational reply.

    The prompt includes recent conversation history so the model carries
    context across turns. Returns the model's response text, or None when
    Ollama is offline, the model is missing, or the reply is empty/failed.
    """
    payload = {
        "model": _ollama_model(),
        "prompt": _build_ollama_prompt(text or ""),
        "system": OLLAMA_SYSTEM_PROMPT,
        "stream": False,
        "options": {"temperature": 0.7, "num_predict": 300},
    }
    req = urllib.request.Request(
        f"{OLLAMA_BASE}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        out = (data.get("response") or "").strip()
        if out:
            _remember(text or "", out)
        return out or None
    except Exception:
        return None


def _needs_web_context(text):
    """True when the prompt explicitly asks for live/current/web knowledge."""
    t = (text or "").lower()
    return any(h in t for h in _OLLAMA_WEB_CONTEXT_HINTS)


# ---------------------------------------------------------------------------
# Gemini LLM (tier 2 — web-capable fallback when Ollama is down/weak)
# ---------------------------------------------------------------------------

# Reads GEMINI_API_KEY from the environment. Set it in a local .env file
# (git-ignored) or export it in the shell — never hardcode it in source.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
# NOTE: gemini-2.5-flash is decommissioned for new accounts (HTTP 404). The
# working replacement on this key is gemini-3.6-flash.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

# JARVIS persona injected as context for natural, on-brand answers.
JARVIS_PERSONA = (
    "You are JARVIS, the user's personal macOS AI assistant addressed as 'sir'. "
    "Be concise, sharp, and helpful — 1 or 2 sentences max. Never claim to have "
    "performed a system action; system actions are handled by local handlers."
)


@app.after_request
def add_header(response):
    """Kill all caching so browsers/Flask never serve stale files."""
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


# ---------------------------------------------------------------------------
# Text-to-Speech — background, non-blocking, via macOS native `say`
# ---------------------------------------------------------------------------

def speak(text):
    """Speak text aloud in the background without blocking the response.

    Uses the built-in macOS `say` command so no extra Python packages are
    required. Runs asynchronously; failures are silently ignored.
    """
    if not text or VOICE_MUTED["muted"]:
        return
    try:
        subprocess.Popen(
            ["say", "-v", TTS_VOICE, text],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(cmd):
    """Run a shell command list and return stripped stdout, or None."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, check=False).stdout.strip()
    except Exception:
        return None


def _osascript(script):
    """Run an AppleScript snippet via osascript."""
    return _run(["osascript", "-e", script])


def _fire_and_forget(cmd):
    """Run a command list asynchronously; used for safe fire-and-forget actions."""
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def _ratio(a, b):
    """0..1 similarity between two strings."""
    return difflib.SequenceMatcher(None, a, b).ratio()


def _alias_hit(text, alias):
    """True if alias (or a close typo of it) appears as a word in the text."""
    if not alias:
        return False
    # Word-boundary match avoids false positives like "yt" inside "python".
    if re.search(r"\b" + re.escape(alias) + r"\b", text):
        return True
    # Only fuzzy-match reasonably long words to avoid false positives.
    if len(alias) < 5:
        return False
    for token in re.findall(r"[a-zçğıöşü]+", text):
        if _ratio(alias, token) >= 0.8:
            return True
    return False


# ---------------------------------------------------------------------------
# Gemini LLM (tier 2 — web-capable fallback when Ollama is down/weak)
# ---------------------------------------------------------------------------

def _gemini_chat(text):
    """Ask Gemini for a natural conversational reply, or None on failure."""
    if not GEMINI_API_KEY:
        return None

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": f"{JARVIS_PERSONA}\n\nUser: {text}\nJARVIS:"}
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 500,
        },
    }

    req = urllib.request.Request(
        GEMINI_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": GEMINI_API_KEY,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        text_out = (data["candidates"][0]["content"]["parts"][0].get("text") or "").strip()
        return text_out or None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# News Fetcher (Google News RSS)
# ---------------------------------------------------------------------------

NEWS_FEEDS = {
    "tr": "https://news.google.com/rss?hl=tr&gl=TR&ceid=TR:tr",
    "en": "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en",
}

NEWS_TRIGGERS_EN = ("news", "world news", "headline", "headlines", "breaking", "latest")


def _fetch_news(text):
    """Parse Google News RSS and return the top 3 headlines as a string."""
    tr_keywords = ("haber", "haberler", "gündem", "son dakika",
                   "türkiye", "turkey news", "güncel")
    lang = "tr" if any(k in text.lower() for k in tr_keywords) else "en"
    feed_url = NEWS_FEEDS[lang]

    try:
        req = urllib.request.Request(
            feed_url,
            headers={"User-Agent": "Mozilla/5.0 JARVIS/1.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            xml_data = resp.read().decode("utf-8")
        root = ET.fromstring(xml_data)
        items = root.findall(".//item")[:3]
        headlines = []
        for item in items:
            title_el = item.find("title")
            if title_el is not None and title_el.text:
                headlines.append(title_el.text.strip())
        if not headlines:
            return None
        numbered = "\n".join(f"  {i+1}. {h}" for i, h in enumerate(headlines))
        reply = f"Here are the top headlines right now, sir:\n{numbered}"
        speak(reply)
        return reply
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Live Currency & Crypto Tracker (open.er-api.com + CoinGecko, no API keys)
# ---------------------------------------------------------------------------

ER_API_BASE = "https://open.er-api.com/v6/latest/"
COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd,try"


def _fetch_currency_rates():
    """Fetch USD/TRY and EUR/TRY plus BTC (USD + TRY) as a dict, or {}."""
    rates = {}
    try:
        for base in ("USD", "EUR"):

            def _get(url):
                req = urllib.request.Request(
                    url, headers={"User-Agent": "Mozilla/5.0 JARVIS/1.0"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    return json.loads(resp.read().decode("utf-8"))

            data = _get(ER_API_BASE + base)
            if data.get("result") == "success":
                try_rate = data.get("rates", {}).get("TRY")
                if try_rate:
                    rates[base + "/TRY"] = round(float(try_rate), 2)
    except Exception:
        pass

    try:
        req = urllib.request.Request(
            COINGECKO_URL, headers={"User-Agent": "Mozilla/5.0 JARVIS/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        btc = data.get("bitcoin", {})
        if "usd" in btc:
            rates["BTC/USD"] = round(float(btc["usd"]), 2)
        if "try" in btc:
            rates["BTC/TRY"] = round(float(btc["try"]), 0)
    except Exception:
        pass

    return rates


def _format_rate(rate, decimals=2):
    """Nicely format a numeric rate for speaking."""
    try:
        return f"{float(rate):,.{decimals}f}"
    except Exception:
        return str(rate)


def _handle_finance(text):
    """Detect currency/crypto queries and return a spoken price reply."""
    clean = text.lower().strip()
    want_usd = bool(re.search(r"\b(usd|dollar|dolar)\b", clean)) or "dollar rate" in clean
    want_eur = bool(re.search(r"\b(eur|euro)\b", clean))
    want_btc = bool(re.search(r"\b(btc|bitcoin|crypto)\b", clean))
    if not (want_usd or want_eur or want_btc):
        return None

    rates = _fetch_currency_rates()
    parts = []
    if want_usd and "USD/TRY" in rates:
        parts.append(f"USD is currently {_format_rate(rates['USD/TRY'])} TRY")
    if want_eur and "EUR/TRY" in rates:
        parts.append(f"EUR is currently {_format_rate(rates['EUR/TRY'])} TRY")
    if want_btc:
        if "BTC/USD" in rates:
            parts.append(f"Bitcoin is trading at {_format_rate(rates['BTC/USD'])} USD")
        if "BTC/TRY" in rates:
            parts.append(f"about {_format_rate(rates['BTC/TRY'], 0)} TRY")

    if not parts:
        return None
    reply = ". ".join(parts) + ", sir."
    speak(reply)
    return reply


# ---------------------------------------------------------------------------
# Lightweight Web Search Snippet (no API keys — DDG Instant Answer + Wikipedia)
# ---------------------------------------------------------------------------

def _web_search_snippet(query, max_chars=250):
    """Return a concise info/snippet for a query without needing an API key.

    Cascade: DuckDuckGo Instant Answer REST API first, then the Wikipedia
    search API. Returns the first meaningful snippet, or None.
    """
    q = urllib.parse.quote(query)

    # 1) DuckDuckGo Instant Answer API — clean Answers / AbstractText.
    try:
        req = urllib.request.Request(
            f"https://api.duckduckgo.com/?q={q}&format=json&no_html=1&skip_disambig=1",
            headers={"User-Agent": "Mozilla/5.0 JARVIS/1.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        for field in ("AbstractText", "Answer"):
            value = (data.get(field) or "").strip()
            if value:
                return html.unescape(value)[:max_chars]
    except Exception:
        pass

    # 2) Wikipedia search API fallback.
    try:
        req = urllib.request.Request(
            f"https://en.wikipedia.org/w/api.php?action=query&list=search"
            f"&srsearch={q}&format=json&srlimit=1&utf8=1",
            headers={"User-Agent": "Mozilla/5.0 JARVIS/1.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        hits = data.get("query", {}).get("search", [])
        if hits:
            snippet = html.unescape(re.sub(r"<[^>]+>", "", hits[0].get("snippet", "")).strip())
            if snippet:
                return snippet[:max_chars]
    except Exception:
        pass

    return None


def _snippet_is_vague(snippet, query):
    """Heuristic: is a snippet too short/repetitive to actually answer the
    question? If so, we'd rather open a web search than read nonsense aloud."""
    if not snippet:
        return True
    if len(snippet) < 40:
        return True
    text = html.unescape(snippet).strip()
    words = re.findall(r"[A-Za-zçğıöşüÇĞİÖŞÜ]+", text)
    if len(words) < 6:
        return True
    # Drop leading "query ..." echoes, e.g. "X X X ..." repeated verbatim.
    words_set = set(w.lower() for w in words)
    echo = sum(1 for w in words if w.lower() in query.lower().split())
    if len(words) >= 4 and echo > len(words) // 2:
        return True
    return False


# ---------------------------------------------------------------------------
# Smart Web & YouTube Search
# ---------------------------------------------------------------------------

# Leading casual/filler phrases stripped before intent parsing so the real
# query survives — "alr cool so can you google cats" -> "google cats".
_FILLER_PREFIXES = (
    "alr cool so", "alright cool so", "aight cool so", "okay cool so",
    "ok cool so", "cool so", "so",
    "no i mean", "no wait", "wait no", "hold on", "hold up",
    "can you", "could you", "would you", "can u",
    "hey jarvis", "ok jarvis", "okay jarvis", "yo jarvis", "jarvis",
)


def _strip_fillers(text, max_iter=6):
    """Remove stacked leading filler phrases from user input."""

    def _apply(cleaned):
        lower = cleaned.lower()
        for filler in _FILLER_PREFIXES:
            if lower == filler:
                return ""
            if lower.startswith(filler + " "):
                return cleaned[len(filler) + 1:].strip()
        return None

    if not text:
        return text or ""
    cleaned = text.strip()
    for _ in range(max_iter):
        nxt = _apply(cleaned)
        if nxt is None:
            break
        cleaned = nxt
        if not cleaned:
            break
    return cleaned


def _extract_search_query(text, prefixes):
    """Strip a leading search-prefix phrase and return the remaining query."""
    for prefix in prefixes:
        if text.startswith(prefix):
            return text[len(prefix):].strip()
    return None


# ---------------------------------------------------------------------------
# Global product / shopping search — any platform, real URLs only
# ---------------------------------------------------------------------------

# Canonical platform -> aliases to recognise inside the prompt.
_PLATFORM_ALIASES = {
    "trendyol": ("trendyol",),
    "amazon": ("amazon",),
    "hepsiburada": ("hepsiburada", "hepsibura", "hep burada"),
    "n11": ("n11", "n 11"),
    "ebay": ("ebay",),
    "google shopping": ("google shopping", "shop on google", "shopping"),
}

# Turkish-market platforms convert the query to Turkish for useful results.
_TR_PLATFORMS = {"trendyol", "hepsiburada", "n11", "amazon"}

_PLATFORM_NAMES = {
    "trendyol": "Trendyol",
    "amazon": "Amazon",
    "hepsiburada": "Hepsiburada",
    "n11": "N11",
    "ebay": "eBay",
    "google shopping": "Google Shopping",
}

_PLATFORM_HOMEPAGES = {
    "trendyol": "https://www.trendyol.com",
    "amazon": "https://www.amazon.com.tr",
    "hepsiburada": "https://www.hepsiburada.com",
    "n11": "https://www.n11.com",
    "ebay": "https://www.ebay.com",
    "google shopping": "https://www.google.com/search?tbm=shop",
}

_PLATFORM_URLS = {
    "trendyol": "https://www.trendyol.com/sr?q={q}",
    "amazon": "https://www.amazon.com.tr/s?k={q}",
    "hepsiburada": "https://www.hepsiburada.com/ara?q={q}",
    "n11": "https://www.n11.com/arama?q={q}",
    "ebay": "https://www.ebay.com/sch/i.html?_nkw={q}",
    "google shopping": "https://www.google.com/search?tbm=shop&q={q}",
}

# Verbs/fillers stripped out of the prompt while building the query.
_SHOPPING_VERBS = (
    "i want to buy", "find me ", "show me ", "give me ", "get me ",
    "look for ", "look up ", "i want ", "i need ", "want ", "need ",
    "shop for ", "buy ", "order ", "purchase ", "compare ", "search for ",
    "search ", "find ", "show ", "get ", "open ", "go to ", "just ",
    "only ", "ara ", "bul ", "söyle ", "istersem ", "satın al ", "satin al ",
)

# Word-boundary triggers that turn a platform-less prompt into a shopping
# search (default platform: Google Shopping).
_SHOPPING_TRIGGERS = (
    "shop for ", "find me ", "get me ", "buy ", "order ", "purchase ",
    "search for ", "compare ", "i want to buy", "satın al ", "satin al ",
)

_SHOPPING_STOP = {
    "the", "a", "an", "on", "in", "for", "from", "to", "of", "and", "or",
    "please", "lütfen", "bir", "bana", "en", "acil", "com", "site", "web",
    "website", "product", "products", "ürün", "urun", "item", "items",
}

# EN -> TR (ASCII) shopping terms so Turkish platforms return good results.
_EN_TR_SHOPPING = {
    # colours
    "brown": "kahverengi", "black": "siyah", "white": "beyaz", "blue": "mavi",
    "red": "kirmizi", "green": "yesil", "yellow": "sari", "pink": "pembe",
    "orange": "turuncu", "purple": "mor", "gray": "gri", "grey": "gri",
    "navy": "lacivert", "gold": "altin", "silver": "gumus",
    # device accessories & fashion
    "case": "kilif", "cover": "kilif", "phone": "telefon", "headphones": "kulaklik",
    "cable": "kablo", "screen": "ekran", "camera": "kamera", "battery": "pil",
    "strap": "kayis", "band": "kayis", "bag": "canta", "shoes": "ayakkabi",
    "t-shirt": "tisort", "tshirt": "tisort", "jacket": "ceket", "hoodie": "kapuson",
    "watch": "saat", "laptop": "laptop", "car": "araba",
}

# ASCII-fold Turkish diacritics for TR platform URLs ("kılıf" -> "kilif").
_TR_FOLD = str.maketrans("çğıöşüÇĞİÖŞÜâî", "cgiosuCGIOSUai")

# Query token ordering mirrors the example "iphone+13+kahverengi+kilif":
# schematic words first, then color, then the product category last.
_SHOPPING_COLORS = {"kahverengi", "siyah", "beyaz", "mavi", "kirmizi", "yesil",
                    "sari", "pembe", "turuncu", "mor", "gri", "lacivert",
                    "altin", "gumus"}
_SHOPPING_CATEGORIES = {"kilif", "telefon", "kulaklik", "kablo", "ekran", "kamera",
                        "pil", "kayis", "canta", "ayakkabi", "tisort", "ceket",
                        "kapuson", "saat", "laptop", "araba"}


def _fold_tr(word):
    """Fold Turkish diacritics to ASCII for URL-safe shopping slugs."""
    return word.translate(_TR_FOLD)


def _detect_platform(text):
    """Return the canonical platform mentioned in the prompt, or None."""
    t = " " + (text or "").lower() + " "
    for platform, aliases in _PLATFORM_ALIASES.items():
        if any(a in t for a in aliases):
            return platform
    return None


def _looks_like_shopping(text):
    """Unambiguous shopping verbs with no platform still mean a product search."""
    t = (text or "").lower()
    return any(re.search(r"\b" + re.escape(x.strip()) + r"\b", t)
               for x in _SHOPPING_TRIGGERS)


def _handle_product_search(text, platform):
    """Build + open a real shopping URL; never fabricate product data.

    Recognizes Trendyol / Amazon / Hepsiburada / N11 / eBay / Google
    Shopping. When no platform is named but the prompt is an unambiguous
    shopping request, defaults to Google Shopping.
    """
    clean = (text or "").lower().strip()
    if platform is None:
        platform = _detect_platform(clean)
    if platform is None:
        if not _looks_like_shopping(clean):
            return None
        platform = "google shopping"
    elif re.search(r"\b(video|movie|film|song)\b", clean):
        # Streaming/media asks ("amazon prime video") are not shopping.
        return None

    # Strip platform aliases, shopping verbs, and filler words.
    parts = clean
    for alias in _PLATFORM_ALIASES.get(platform, ()):
        parts = parts.replace(alias, " ")
    if platform == "google shopping":
        parts = re.sub(r"\b(shopping|shop)\b", " ", parts)
    for verb in _SHOPPING_VERBS:
        parts = re.sub(re.escape(verb.strip()) + r"\b\s*", " ", parts)
    tokens = [t for t in re.findall(r"[a-zçğıöşü0-9.\-]+", parts)
              if t not in _SHOPPING_STOP]

    name = _PLATFORM_NAMES[platform]
    if not tokens:
        webbrowser.open(_PLATFORM_HOMEPAGES[platform])
        reply = f"Opening {name} in your browser, sir."
        speak(reply)
        _remember(text, reply)
        return reply

    if platform in _TR_PLATFORMS:
        core, colors, cats = [], [], []
        for token in tokens:
            tr = _fold_tr(_EN_TR_SHOPPING.get(token, token))
            if tr in _SHOPPING_COLORS:
                colors.append(tr)
            elif tr in _SHOPPING_CATEGORIES:
                cats.append(tr)
            else:
                core.append(tr)
        q = "+".join(core + colors + cats)
    else:
        q = "+".join(tokens)

    url = _PLATFORM_URLS[platform].format(q=urllib.parse.quote(q, safe="+"))
    webbrowser.open(url)

    human = [("iPhone" if t == "iphone" else t.title()) for t in tokens]
    if human and human[-1].lower() == "case":
        human[-1] = "Cases"
    phrase = " ".join(human)
    reply = f"Opening search results for {phrase} on {name} in your browser, sir."
    speak(reply)
    _remember(text, reply)
    return reply


# Raw template placeholders ([Brand Name], [Rating], <Brand>...) must never
# be spoken. Anything that still contains one counts as an unfetched response.
_PLACEHOLDER_RE = re.compile(r"\[[A-Za-z][\w &'’.-]{0,24}\]|<[A-Za-z][\w ]*>")


def _contains_placeholder(text):
    """True if the text still holds an unfilled template placeholder."""
    return bool(_PLACEHOLDER_RE.search(text or ""))


def _handle_search(text):
    """Route 'search google/youtube for X' and 'play X on youtube' queries."""
    clean = text.lower().strip()

    # Product/shopping prompts that name a platform beat the generic search
    # bucket so they build a real product URL instead of a dictionary snippet.
    platform = _detect_platform(clean)
    if platform:
        product_reply = _handle_product_search(clean, platform)
        if product_reply:
            return product_reply

    # Direct runtime picks: "newest [X] video", "latest [X] video",
    # "open a [X] video" — opens a filtered YouTube search for the topic.
    video_patterns = (
        r"^(?:open|play|show me|find|get the|get)(?: me)? (?:a |the )?(?:newest|latest|most recent|new) (.+) video$",
        r"^(?:newest|latest|most recent) (.+) video$",
        r"^open a (.+) video$",
    )
    for pattern in video_patterns:
        m = re.match(pattern, clean)
        if m:
            topic = m.group(1).strip()
            if topic and len(topic.split()) <= 8:
                url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(f"{topic} latest video")
                webbrowser.open(url)
                reply = f"Opening the latest {topic.title()} video on Youtube, sir."
                speak(reply)
                return reply

    # YouTube searches: "search youtube for X", "play X on youtube",
    # "play X on yt", "youtube X".
    yt_prefixes = ("search youtube for ", "search on youtube for ", "search on youtube ")
    yt_play_pattern = re.match(r"^play (.+) (?:on|in) youtube$", clean)
    yt_on_pattern = re.match(r"^(?:search )?(.+) on youtube$", clean)
    yt_query = _extract_search_query(clean, yt_prefixes)
    if yt_query:
        url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(yt_query)
        webbrowser.open(url)
        reply = f"Searching Youtube for '{yt_query.title()}', sir."
        speak(reply)
        return reply
    if yt_play_pattern:
        query = yt_play_pattern.group(1).strip()
        url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(query)
        webbrowser.open(url)
        reply = f"Playing '{query.title()}' on Youtube, sir."
        speak(reply)
        return reply
    if yt_on_pattern and clean.startswith("play") is False:
        query = yt_on_pattern.group(1).strip()
        # Ignore bare "open youtube" etc — that's handled by the app registry.
        if query not in ("open", "youtube", "yo youtube"):
            url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(query)
            webbrowser.open(url)
            reply = f"Searching Youtube for '{query.title()}', sir."
            speak(reply)
            return reply

    # Google searches: "search google for X", "google X", "search the web for X".
    gg_prefixes = ("search google for ", "search google ", "search the web for ",
                   "google search for ", "google ")
    gg_query = _extract_search_query(clean, gg_prefixes)
    if gg_query:
        url = "https://www.google.com/search?q=" + urllib.parse.quote(gg_query)
        webbrowser.open(url)
        reply = f"Searching Google for '{gg_query.title()}', sir."
        speak(reply)
        return reply

    # Platform-less shopping intent lands here (after the dedicated search
    # handlers) and defaults to Google Shopping.
    product_reply = _handle_product_search(clean, None)
    if product_reply:
        return product_reply

    return None


# ---------------------------------------------------------------------------
# Tutorial / "How to" Detection (opens a browser search; no text snippets)
# ---------------------------------------------------------------------------

TUTORIAL_PATTERNS = (
    r"\bhow to\b",
    r"\bhow do i\b",
    r"\bhow can i\b",
    r"\bhow do you\b",
    r"\btutorials?\b",
    r"\bguides?\b",
    r"\blessons?\b",
    r"\bcourses?\b",
    r"\blearn how to\b",
    r"\bnasıl yapılır\b",  # tr: how is it done
    r"\bdersi\b",          # tr: lesson/class (suffix form, e.g. "python dersi")
    r"\bders\b",           # tr: lesson/class
    r"\böğren\b",          # tr: learn
)


def _tutorial_topic(text):
    """Extract the core topic from a how-to/tutorial phrase.

    Handles topics in several orders: "how to X", "show me a tutorial for
    X", "guide me through X", "X dersi", "X tutorials", "nasıl yapılır X".
    Returns None if no usable topic can be extracted.
    """
    clean = (text or "").lower().strip()
    topic_class = r"[a-zA-Z0-9çğıöşüÇĞİÖŞÜ][a-zA-Z0-9 çğıöşüÇĞİÖŞÜ'’&.#+.-]{1,40}"

    # Leading how-to patterns: how to X / how do i X / learn how to X
    m = re.search(r"\b(?:how (?:do |can |should )?i |how to |how do you |how would you |learn how to )(" + topic_class + r")", clean)
    if m:
        return m.group(1).strip().title()

    # Tutorial keywords: "tutorial on X", "guide to X", "guide me through X".
    for kw in ("tutorial", "guide", "lesson", "course", "videoları",
               "videos", "video", "ders"):
        pattern = (r"\b" + re.escape(kw) + r"\s+(?:(?:for|on|about|of|in|into|at)\s+)?(?:"
                   r"me\s+(?:through|to|on|with)\s+)?(" + topic_class + r")")
        m = re.search(pattern, clean)
        if m:
            return m.group(1).strip().title()

    # Topic before keyword: "X tutorials", "X lessons", "X dersi".
    m = re.search(r"(" + topic_class + r")\s+(?:tutorials?|lessons?|courses?|videos?|guides?|dersi)\b", clean)
    if m:
        return m.group(1).strip().title()

    # Turkish: nasıl yapılır X  /  X nasıl yapılır  /  X öğren  /  X dersi
    m = re.search(r"\b(nasıl yapılır|nasıl yapilir|öğren|öyren)\s+(" + topic_class + r")", clean)
    if m:
        return m.group(2).strip().title()
    m = re.search(r"(" + topic_class + r")\s+(nasıl yapılır|nasıl yapilir|dersi|öğren|yapmayı öğren)", clean)
    if m:
        topic = m.group(1).strip()
        for filler in ("bana", "bize", "show me", "teach me", "learn", "how", "to"):
            if topic.startswith(filler + " "):
                topic = topic[len(filler) + 1:].strip()
        return topic.title() if topic else None

    return None


def _handle_tutorial(text):
    """If the prompt asks for a how-to/tutorial, open a direct YouTube search."""
    clean = text.lower().strip()
    if not any(re.search(p, clean) for p in TUTORIAL_PATTERNS):
        return None

    # Only treat it as a tutorial intent if we can extract a real topic —
    # otherwise let the normal search/Gemini flow handle it.
    topic = _tutorial_topic(clean)
    if not topic:
        return None

    # Skip trivial/short topics like "to", "i", "it".
    if len(topic.split()) < 1 or topic.lower() in ("to", "i", "it", "a", "an", "the"):
        return None

    url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(f"{topic} tutorial")
    webbrowser.open(url)
    reply = f"Opening a tutorial for {topic} in your browser, sir."
    speak(reply)
    return reply


# ---------------------------------------------------------------------------
# Media & Spotify Controls (AppleScript)
# ---------------------------------------------------------------------------

def _spotify_action(action):
    """Send a Spotify AppleScript command. Supported: next, previous, playpause."""
    cmds = {
        "next": 'tell application "Spotify" to next track',
        "previous": 'tell application "Spotify" to previous track',
        "playpause": 'tell application "Spotify" to playpause',
    }
    script = cmds.get(action)
    if not script:
        return "I couldn't perform that action, sir."
    _osascript(script)
    labels = {
        "next": "Playing the next track, sir.",
        "previous": "Going back to the previous track, sir.",
        "playpause": "Pausing the music, sir." if "pause" in "pause" else "Resuming the music, sir.",
    }
    reply = labels[action]
    if action == "playpause":
        # Can't know the resulting state; keep it neutral.
        reply = "Toggling the music, sir."
    speak(reply)
    return reply


# ---------------------------------------------------------------------------
# App & Intent Registry
# ---------------------------------------------------------------------------

OPEN_VERBS = ("open", "launch", "start", "play", "go to", "show me", "run")
BLOCK_VERBS = ("close", "kill", "quit", "stop", "exit", "kapat")

APP_REGISTRY = {
    "youtube": {
        "kind": "web",
        "url": "https://www.youtube.com",
        "aliases": ["youtube", "yutube", "you tube", "yt"],
    },
    "terminal": {
        "kind": "app",
        "app": "Terminal",
        "aliases": ["terminal"],
    },
    "finder": {
        "kind": "app",
        "app": "Finder",
        "aliases": ["finder"],
    },
    "spotify": {
        "kind": "app",
        "app": "Spotify",
        "aliases": ["spotify", "spofity"],
    },
    "chrome": {
        "kind": "app",
        "app": "Google Chrome",
        "aliases": ["chrome", "google chrome"],
    },
}


def _detect_app(text):
    """Return the app key whose alias (or typo) matches the text, else None."""
    for key, spec in APP_REGISTRY.items():
        if any(_alias_hit(text, a) for a in spec["aliases"]):
            return key
    return None


def _open_app(key):
    """Launch/open the requested app or website."""
    spec = APP_REGISTRY[key]
    if spec["kind"] == "web":
        webbrowser.open(spec["url"])
        reply = f"Opening {key.title()} in your browser, sir."
    else:
        _fire_and_forget(["open", "-a", spec["app"]])
        reply = f"Launching {spec['app']}, sir."
    speak(reply)
    return reply


# ---------------------------------------------------------------------------
# System Action Engine — unified DO vs talk classifier + full macOS actions
# ---------------------------------------------------------------------------

# Single-word action verbs an action request can lead with.
_ACTION_VERBS = {
    "open", "launch", "start", "stop", "close", "quit", "play", "pause",
    "resume", "search", "find", "show", "set", "turn", "make", "create",
    "delete", "remove", "rename", "move", "copy", "empty", "lock", "unlock",
    "run", "execute", "capture", "take", "mute", "unmute", "increase",
    "decrease", "raise", "lower", "reduce", "install", "update", "download",
    "print", "enable", "disable", "send", "call", "shutdown", "restart",
    "sleep", "wake", "volume", "brightness", "switch", "change", "go",
    "browse", "translate", "convert", "save", "add", "type", "create",
    "write", "record", "focus", "minimize", "maximize", "hide",
}

# Multi-word action phrases checked before the first-word rule.
_ACTION_PHRASES = (
    "give me ", "get me ", "open up ", "shut down ", "turn off ", "turn on ",
    "turn up ", "turn down ", "set up ", "set the ", "play some",
    "zoom in", "zoom out", "show the ", "find the ", "empty the ",
    "lock the ", "close the ", "stop the ", "start the ", "shut the ",
)


def _is_action_request(text):
    """Return True when the prompt demands we DO something, not just talk."""
    t = (text or "").lower().strip()
    for prefix in ("can you ", "could you ", "will you ", "would you ",
                   "please ", "i need you to ", "i want you to ", "hey ",
                   "yo ", "jarvis ", "sir "):
        if t.startswith(prefix):
            t = t[len(prefix):].strip()
            break
    if not t:
        return False
    if any(t.startswith(p) for p in _ACTION_PHRASES):
        return True
    first = t.split(" ", 1)[0].rstrip(",")
    return first in _ACTION_VERBS


def _read_volume():
    """Current macOS output volume (0-100)."""
    try:
        return int(_osascript("output volume of (get volume settings)") or 50)
    except Exception:
        return 50


def _set_volume(level):
    """Apply and return the clamped macOS output volume (0-100)."""
    level = max(0, min(100, int(level)))
    _osascript(f"set volume output volume {level}")
    return level


def _handle_volume(text):
    """Set / raise / lower the system volume in one execution."""
    clean = (text or "").lower().strip()
    if not re.search(r"\b(volume|ses|sesi|sound)\b", clean):
        return None
    pct = re.search(r"(\d{1,3})\s*(?:%|percent)?", clean)
    if re.search(r"(increase|raise|bump|louder|\bturn up\b|\bup\b|artır|yükselt|daha yüksek)", clean):
        target = _read_volume() + int(pct.group(1) if pct else 10)
    elif re.search(r"(decrease|lower|reduce|quieter|\bturn down\b|\bdown\b|kıs|azalt|düşür|daha kısık)", clean):
        target = _read_volume() - int(pct.group(1) if pct else 10)
    elif re.search(r"(set|make|adjust|change|get to)", clean) and pct:
        target = int(pct.group(1))
    else:
        return None
    level = _set_volume(target)
    reply = f"Volume set to {level} percent, sir."
    speak(reply)
    _remember(text, reply)
    return reply


_FOLDER_ALIASES = {
    "downloads": (os.path.expanduser("~/Downloads"), ("downloads", "indirilenler", "indirilen")),
    "desktop": (os.path.expanduser("~/Desktop"), ("desktop", "masaüstü", "masaustu")),
    "documents": (os.path.expanduser("~/Documents"), ("documents", "dokümanlar", "dokumanlar")),
    "pictures": (os.path.expanduser("~/Pictures"), ("pictures", "photos", "fotoğraflar", "fotograflar")),
    "music": (os.path.expanduser("~/Music"), ("music", "müzik", "muzik")),
    "movies": (os.path.expanduser("~/Movies"), ("movies", "videos")),
    "applications": ("/Applications", ("applications", "apps", "uygulamalar")),
    "home": (os.path.expanduser("~"), ("home folder", "home directory")),
}


def _handle_open_location(text):
    """Open a well-known macOS folder without making the user do it."""
    clean = (text or "").lower().strip()
    if not re.search(r"\b(open|launch|show)\b", clean):
        return None
    for name, (path, aliases) in _FOLDER_ALIASES.items():
        if any(a in clean for a in aliases):
            os.makedirs(path, exist_ok=True)
            _fire_and_forget(["open", path])
            reply = f"Opening {name} for you, sir."
            speak(reply)
            _remember(text, reply)
            return reply
    return None


_OPENABLE_EXTS = (
    "pdf", "txt", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "pages",
    "numbers", "key", "png", "jpg", "jpeg", "gif", "heic", "mp3", "mp4",
    "mov", "aiff", "wav", "zip", "dmg", "csv", "rtf", "md", "json", "py",
    "js", "html",
)


def _handle_open_path(text):
    """Open an absolute path, or a file with a recognizable extension."""
    clean = (text or "").lower().strip()
    if not re.search(r"\b(open|launch|show)\b", clean):
        return None
    m = re.search(
        r"\b(?:open|launch|show)\s+[\"'`]?([^\s\"'`]+\.(?:"
        + "|".join(_OPENABLE_EXTS) + r"))[\"'`]?", clean)
    m2 = re.search(r"\b(?:open|launch|show)\s+(/[\w~./@ %\-]+)", clean)
    target = m.group(1) if m else (m2.group(1) if m2 else "")
    if not target:
        return None
    path = os.path.expanduser(target)
    if not os.path.exists(path):
        return None
    _fire_and_forget(["open", path])
    reply = f"Opening {os.path.basename(path)}, sir."
    speak(reply)
    _remember(text, reply)
    return reply


def _handle_create_item(text):
    """Create a file or folder on the Desktop in one execution."""
    clean = (text or "").lower().strip()
    if not re.search(r"(create|make|mkdir|oluştur|olustur)", clean):
        return None
    m = re.search(
        r"(?:create|make|mkdir|oluştur|olustur)\s+(?:a |new |bir |yeni )?"
        r"(folder|directory|klasör|klasor|file|dosya)"
        r"(?:\s+(?:named|called|adında|adıyla|adli|adlı))?\s+[\"'`]?([^\"'`]+?)[\"'`]?\s*$",
        clean)
    if not m:
        return None
    kind, name = m.group(1), m.group(2).strip()
    path = os.path.join(os.path.expanduser("~/Desktop"), name.strip("/\\"))
    try:
        if kind in ("file", "dosya"):
            with open(path, "w") as fh:
                fh.write("")
            reply = f"Created the {kind} '{name}' on your desktop, sir."
        else:
            os.makedirs(path, exist_ok=True)
            reply = f"Created the {kind} '{name}' on your desktop, sir."
    except Exception:
        return None
    speak(reply)
    _remember(text, reply)
    return reply


def _handle_open_domain(text):
    """Open a bare domain (github.com, reddit.com) directly in the browser."""
    clean = (text or "").lower().strip()
    if not re.search(r"\b(open|visit|launch|go to)\b", clean):
        return None
    m = re.search(r"\b(?:open|visit|launch|go to)\s+([a-z0-9\-]+(?:\.[a-z]{2,})+)(?:[/?#]\S*)?", clean)
    if not m:
        return None
    domain = m.group(1)
    webbrowser.open("https://" + domain)
    reply = f"Opening {domain}, sir."
    speak(reply)
    _remember(text, reply)
    return reply


def _handle_terminal_run(text):
    """Execute a command inside macOS Terminal in one shot."""
    clean = (text or "").lower().strip()
    if "terminal" not in clean:
        return None
    m = re.search(r"\brun\b\s+([^,]+?)\s+\bin\b\s+(?:the\s+)?terminal\b", clean)
    or_ = re.search(r"\bin\b\s+(?:the\s+)?terminal\b\s*[,:]?\s*(?:run\s+)?([^,]+?)\s*$", clean)
    cmd = (m.group(1).strip() if m else (or_.group(1).strip() if or_ else ""))
    if not cmd or len(cmd) > 200:
        return None
    safe_cmd = cmd.replace("\\", "\\\\").replace('"', '\\"')
    _fire_and_forget(["osascript", "-e",
                      f'tell application "Terminal" to do script "{safe_cmd}"'])
    reply = f"Executed '{cmd}' in Terminal, sir."
    speak(reply)
    _remember(text, reply)
    return reply


def _handle_default_action(text):
    """Residual action intent: never advise, always perform something.

    Maps playback/stream asks to YouTube, image asks to Google Images,
    and everything else to a direct browser search — then confirms.
    """
    clean = (text or "").lower().strip()
    if not _is_action_request(clean):
        return None
    if re.match(r"^(play|watch|listen)( to)? ", clean):
        topic = re.sub(r"^(play|watch|listen)( to)?\s+", "", clean).strip()
        if not topic:
            return None
        url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(topic)
        reply = f"Opening {topic.title()} for you, sir."
    elif re.match(r"^show me (?:a |an |the )?(picture|photo|image) of ", clean):
        topic = re.sub(r"^show me (?:a |an |the )?(picture|photo|image) of\s+", "", clean).strip()
        url = "https://www.google.com/search?tbm=isch&q=" + urllib.parse.quote(topic)
        reply = f"Showing images of {topic.title()}, sir."
    else:
        url = "https://www.google.com/search?q=" + urllib.parse.quote(clean)
        reply = f"Opening search results for '{clean.title()}', sir."
    webbrowser.open(url)
    speak(reply)
    _remember(text, reply)
    return reply


# ---------------------------------------------------------------------------
# System Handlers
# ---------------------------------------------------------------------------

def _system_report():
    """Live CPU / RAM / battery telemetry."""
    try:
        import psutil
    except Exception:
        return "System telemetry is momentarily unavailable, sir."
    cpu = psutil.cpu_percent(interval=0.5)
    mem = psutil.virtual_memory()
    reply = f"System Telemetry — CPU: {cpu}% | RAM: {mem.percent}% ({mem.used // (1024 ** 3)} GB used)"
    battery = psutil.sensors_battery()
    if battery is not None:
        state = "charging" if battery.power_plugged else "on battery"
        reply += f" | Battery: {battery.percent}% ({state})"
    speak(reply)
    return reply


def _gather_telemetry():
    """Structured, JSON-safe telemetry snapshot for the live widgets."""
    info = {
        "cpu": 0,
        "ram_percent": 0,
        "ram_used_gb": 0,
        "ram_total_gb": 0,
        "battery_percent": None,
        "battery_charging": None,
        "time": datetime.datetime.now().strftime("%I:%M %p"),
        "date": datetime.datetime.now().strftime("%A, %B %d, %Y"),
        "gemini_ready": bool(GEMINI_API_KEY),
    }
    try:
        import psutil
        info["cpu"] = round(psutil.cpu_percent(interval=None) or 0, 1)
        info["ram_percent"] = round(psutil.virtual_memory().percent, 1)
        info["ram_used_gb"] = round(psutil.virtual_memory().used / (1024 ** 3), 1)
        info["ram_total_gb"] = round(psutil.virtual_memory().total / (1024 ** 3), 1)
        battery = psutil.sensors_battery()
        if battery is not None:
            info["battery_percent"] = round(battery.percent, 0)
            info["battery_charging"] = bool(battery.power_plugged)
    except Exception:
        pass
    return info


# ---------------------------------------------------------------------------
# Conversational Knowledge Base
# ---------------------------------------------------------------------------

CONVERSATIONAL = {
    "greetings": {
        "patterns": ["hello", "hi", "hey there", "good morning", "good afternoon", "good evening", "selam", "merhaba"],
        "responses": [
            "Hello Ozan. All systems are fully operational.",
            "At your service, sir. What shall we tackle today?",
            "Good to see you. JARVIS online and ready.",
        ],
    },
    "status": {
        "patterns": ["how are you", "how are you doing", "whats up", "status", "what's up"],
        "responses": [
            "Running at peak performance, sir.",
            "All systems are healthy and responsive.",
            "Operating smoothly. What do you need?",
        ],
    },
    "identity": {
        "patterns": ["who are you", "what are you", "your name", "what's your name", "what is your name"],
        "responses": [
            "I am JARVIS, your personal macOS AI assistant.",
            "JARVIS at your service — built to command your workspace.",
        ],
    },
    "thanks": {
        "patterns": ["thanks", "thank you", "thankyou", "ty", "teşekkür", "teşekkürler", "sağol", "sagol"],
        "responses": [
            "You're welcome, sir.",
            "Always at your service.",
            "Anytime, Ozan.",
        ],
    },
    "capabilities": {
        "patterns": ["what can you do", "help", "commands", "features", "abilities"],
        "responses": [
            "I can open apps and websites — try 'open terminal', 'open youtube' or 'open spotify' — control the music with 'next song' or 'pause music', search Youtube or Google, capture the screen, empty the trash, and check system status. How can I assist, sir?",
        ],
    },
    "boredom": {
        "patterns": ["i'm bored", "im bored", "i am bored", "bored", "so bored", "what should i do", "what can i do", "what do i do now"],
        "responses": [
            "How about playing some music, checking YouTube, or taking a quick system break, sir?",
            "Feeling restless, sir? I can start some music, find a good Youtube video, or you can take a quick system break.",
        ],
    },
}

FALLBACK_RESPONSES = [
    "I'm not sure I caught that, sir. Try 'open terminal', 'system check', 'next song', or ask 'what can you do'.",
    "That request is outside my current command set. I can open apps, control music, search the web, and check system status.",
    "Understood — though I don't have a handler for that yet. Try a system command like 'open spotify' or 'time'.",
]


# ---------------------------------------------------------------------------
# Smart Response Engine
# ---------------------------------------------------------------------------

def generate_smart_response(text):
    """Route user input through the typo-tolerant intent engine."""
    stripped = _strip_fillers(text or "")
    clean = stripped.lower().strip()
    if not clean:
        return "I didn't catch that, sir. How may I help you?"

    # ── Tutorial / "how to" (open browser directly, skip snippets) ───────
    # Runs first so a "how to X" prompt never accidentally triggers the
    # real command behind X (e.g. "how do I empty the trash").
    tutorial_reply = _handle_tutorial(clean)
    if tutorial_reply:
        return tutorial_reply

    # ── Clear chat (UI handles visual clearing; backend acks) ────────────
    if re.search(r"\bclear (the )?chat\b", clean):
        reply = "Chat cleared."
        speak(reply)
        return reply

    # ── Empty trash ──────────────────────────────────────────────────────
    if re.search(r"\b(empty|clear) (the )?trash\b", clean):
        _osascript('tell application "Finder" to empty trash')
        reply = "Trash emptied, sir."
        speak(reply)
        return reply

    # ── Screenshot (copies selected area to clipboard) ───────────────────
    if (re.search(r"\bscreenshot\b|\bscreen shot\b|\bscreen capture\b", clean)
            or re.search(r"capture (the )?(screen|display)", clean)
            or "ekran görüntüsü" in clean):
        try:
            subprocess.run(["screencapture", "-c", "-u"], check=False)
            reply = "Screenshot captured and copied to the clipboard, sir."
        except Exception:
            reply = "I couldn't capture the screenshot, sir."
        speak(reply)
        return reply

    # ── Lock screen ──────────────────────────────────────────────────────
    if (re.search(r"\block screen\b|\block (the |my )?(screen|display)\b", clean)
            or "ekranı kilitle" in clean or "ekrani kilitle" in clean):
        try:
            subprocess.run(["pmset", "displaysleepnow"], check=False)
            reply = "Accessing the screen now, sir."
        except Exception:
            reply = "I couldn't lock the screen, sir."
        speak(reply)
        return reply

    # ── Live news (Google News RSS, non-LLM) ─────────────────────────────
    # A "latest/newest [X] video" ask reads like a video request, not a news
    # request, even though "latest" is a generic news trigger.
    video_ask = bool(re.search(r"\b(?:newest|latest|most recent)\b .+? video\b|^open a .+ video$", clean))
    news_latin = any(re.search(r"\b" + re.escape(k) + r"\b", clean) for k in NEWS_TRIGGERS_EN)
    news_tr = any(k in clean for k in ("haber", "haberler", "gündem",
                                       "son dakika", "türkiye", "güncel"))
    if (news_latin or news_tr) and not video_ask:
        news = _fetch_news(clean)
        if news:
            return news

    # ── Live currency & crypto tracker ────────────────────────────────────
    finance_reply = _handle_finance(clean)
    if finance_reply:
        return finance_reply

    # ── Smart web / YouTube search ───────────────────────────────────────
    search_reply = _handle_search(clean)
    if search_reply:
        return search_reply

    # ── Spotify media controls ───────────────────────────────────────────
    if _alias_hit(clean, "next song") or _alias_hit(clean, "next track") or re.search(r"\bnext\b.*\b(song|track)\b", clean):
        return _spotify_action("next")
    if re.search(r"\bprevious (song|track)\b", clean) or _alias_hit(clean, "previous song") or _alias_hit(clean, "previous track"):
        return _spotify_action("previous")
    if _alias_hit(clean, "pause music") or _alias_hit(clean, "pause") or "stop music" in clean:
        return _spotify_action("playpause")
    if "resume music" in clean or "resume" in clean or "play music" in clean or "unpause" in clean:
        return _spotify_action("playpause")

    # ── Terminal execution (must run before the app registry grabs "terminal")
    terminal_reply = _handle_terminal_run(clean)
    if terminal_reply:
        return terminal_reply

    # ── Open app / website (typo-tolerant) ───────────────────────────────
    app_key = _detect_app(clean)
    if app_key:
        wants_open = any(v in clean for v in OPEN_VERBS)
        is_blocked = any(v in clean for v in BLOCK_VERBS)
        # Open when explicitly asked, or when the app name stands alone.
        if wants_open or (not is_blocked and len(clean.split()) <= 2):
            return _open_app(app_key)

    # ── Audio control (unmute must be checked before mute) ───────────────
    if re.search(r"\bunmute\b", clean) or "sesi aç" in clean or "sound on" in clean:
        _osascript("set volume output muted false")
        reply = "Audio unmuted, sir."
        speak(reply)
        return reply
    if re.search(r"\bmute\b", clean) or "sesi kapat" in clean or "sound off" in clean:
        _osascript("set volume output muted true")
        reply = "Audio muted, sir."
        speak(reply)
        return reply

    # ── Volume level (set / raise / lower) ───────────────────────────────
    volume_reply = _handle_volume(clean)
    if volume_reply:
        return volume_reply

    # ── Files, folders & paths (open/create without manual steps) ────────
    loc_reply = _handle_open_location(clean)
    if loc_reply:
        return loc_reply
    path_reply = _handle_open_path(clean)
    if path_reply:
        return path_reply
    create_reply = _handle_create_item(clean)
    if create_reply:
        return create_reply

    # ── Bare domain / terminal execution ─────────────────────────────────
    domain_reply = _handle_open_domain(clean)
    if domain_reply:
        return domain_reply

    # ── System telemetry ─────────────────────────────────────────────────
    if any(re.search(r"\b" + re.escape(k) + r"\b", clean)
           for k in ["system check", "check system", "telemetry", "specs",
                     "cpu", "ram", "memory", "battery", "batarya"]):
        return _system_report()

    # ── Time & date ─────────────────────────────────────────────────────
    if re.search(r"\b(time|saat|clock)\b", clean):
        now = datetime.datetime.now().strftime("%I:%M %p")
        reply = f"The local time is {now}, sir."
        speak(reply)
        return reply
    if re.search(r"\b(date|tarih)\b", clean) or "today's date" in clean or "todays date" in clean:
        today = datetime.datetime.now().strftime("%A, %B %d, %Y")
        reply = f"Today is {today}, sir."
        speak(reply)
        return reply

    # ── Unified Action Classifier (execution is mandatory, never advice) ─
    # Any remaining DO-request gets performed (play -> YouTube, photos ->
    # images, everything else -> direct web search). We never hand the user
    # manual steps or "visit google.com" instructions.
    action_reply = _handle_default_action(clean)
    if action_reply:
        return action_reply

    # ── Hybrid Brain: Ollama (primary) → Gemini (secondary) ─────────────
    # Only pure conversation/questions reach the LLM.
    llm_reply = None
    if not _needs_web_context(stripped):
        llm_reply = _ollama_chat(stripped or "")
    if not llm_reply:
        llm_reply = _gemini_chat(stripped or "")
    # Never speak raw template placeholders — treat them as a failed fetch and
    # fall through to the snippet/browser path instead.
    if llm_reply and not _contains_placeholder(llm_reply):
        speak(llm_reply)
        return llm_reply

    # ── Local conversational intents (both brains down/empty) ───────────
    # Keep "im bored" / small talk out of DDG-Wiki dictionaries: reply, don't search.
    for intent, data in CONVERSATIONAL.items():
        if any(re.search(r"\b" + re.escape(p) + r"\b", clean) for p in data["patterns"]):
            reply = random.choice(data["responses"])
            speak(reply)
            return reply

    # ── Web search snippet fallback (LLM tiers unavailable) ─────────────
    # Read back a real search result snippet instead of a canned "I don't
    # know" reply; open the browser when the snippet is too short/vague.
    snippet = _web_search_snippet(clean)
    if snippet and not _snippet_is_vague(snippet, clean):
        reply = f"Here's what I found, sir: {snippet}"
        speak(reply)
        return reply

    # ── Direct web search fallback (vague snippet or none) ──────────────
    url = "https://www.google.com/search?q=" + urllib.parse.quote(clean)
    webbrowser.open(url)
    reply = f"Opening search results for '{clean.title()}' in your browser, sir."
    speak(reply)
    return reply

    # ── Polished fallback (never a raw echo) ────────────────────────────
    reply = random.choice(FALLBACK_RESPONSES)
    speak(reply)
    return reply


# ---------------------------------------------------------------------------
# Flask Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/command", methods=["POST"])
def handle_command():
    """Accept {"command": "text"} and return {"status": "success", "message": "..."}."""
    data = request.get_json(silent=True) or {}
    raw_cmd = (data.get("command") or "").strip()

    if not raw_cmd:
        return jsonify({"status": "error", "message": "Empty command"}), 400

    response_text = generate_smart_response(raw_cmd)
    return jsonify({"status": "success", "message": response_text})


@app.route("/api/ping", methods=["GET"])
def ping():
    return jsonify({"status": "success", "message": "pong"})


@app.route("/api/broadcast", methods=["POST"])
def handle_broadcast():
    """Accept {"text": "..."} to have JARVIS speak a message via TTS."""
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if text:
        speak(text)
    return jsonify({"status": "success", "message": "Broadcast sent."})


@app.route("/api/telemetry", methods=["GET"])
def telemetry():
    """Live telemetry snapshot for the frontend telemetry widgets."""
    return jsonify({"status": "success", "telemetry": _gather_telemetry()})


@app.route("/api/voice-mute", methods=["GET", "POST"])
def voice_mute():
    """Get/set the TTS mute flag. POST {"muted": bool} sets it explicitly."""
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        if isinstance(data.get("muted"), bool):
            VOICE_MUTED["muted"] = data["muted"]
        else:
            VOICE_MUTED["muted"] = not VOICE_MUTED["muted"]
    return jsonify({"status": "success", "muted": VOICE_MUTED["muted"]})


ALLOWED_MEDIA_ACTIONS = ("playpause", "next", "previous")


@app.route("/api/media", methods=["POST"])
def media():
    """Drive Spotify quick controls: {"action": "playpause"|"next"|"previous"}."""
    data = request.get_json(silent=True) or {}
    action = (data.get("action") or "").strip()
    if action not in ALLOWED_MEDIA_ACTIONS:
        return jsonify({"status": "error", "message": "Unsupported media action."}), 400
    reply = _spotify_action(action)
    return jsonify({"status": "success", "message": reply})


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)