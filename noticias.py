"""
Noticias y predicción a pocos días para CriptoSenales
Autor: Luis Tranche Casado

Fuentes gratuitas, sin cuenta ni clave:
  · Google Noticias (RSS de búsqueda, también por fechas) en inglés y en español
  · RSS de CoinDesk, Cointelegraph y Decrypt
  · Índice de miedo y codicia del mercado cripto (alternative.me), con historial diario

Qué hace:
  1. Busca los días de los últimos meses con movimientos fuertes del precio (más de
     EVENT_SIGMA desviaciones típicas) y las noticias publicadas esos días: son las
     "noticias que movieron el precio". Mide en cuántos de esos movimientos el tono de
     las noticias coincidió con la dirección del precio (fiabilidad de las noticias
     para esa moneda).
  2. Puntúa el tono de las noticias recientes (positivo / negativo) con un diccionario
     de palabras en inglés y español, y mide cómo evoluciona (últimas 48 h frente a la
     semana).
  3. Predicción a PRED_DAYS días:
       base     = extrapolación de la tendencia reciente: recta ajustada por mínimos
                  cuadrados ponderados a los últimos 20 cierres (los días recientes pesan
                  más), prolongada hacia el futuro con amortiguación (la tendencia pierde
                  fuerza cada día).
       noticias = corrección por el tono y la evolución de las noticias, escalada por la
                  volatilidad de la moneda y por la fiabilidad medida en el punto 1; su
                  efecto se va diluyendo con los días.
       ánimo    = corrección por el cambio del índice de miedo y codicia, con un
                  coeficiente calculado (regresión) sobre el historial de la propia moneda.
     La banda es ±1 desviación típica (≈ 68 % de los casos si el mercado se comporta como
     en el pasado).

No usa Qt: se puede probar aparte. AVISO: es una estimación estadística, no una garantía.
"""

import email.utils
import html
import math
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

DAY_MS = 86_400_000
PRED_DAYS = 5            # días que se predicen
EVENT_LOOKBACK = 120     # días hacia atrás en los que se buscan movimientos fuertes
EVENT_SIGMA = 2.0        # un día es "movimiento fuerte" si |variación| >= 2 desviaciones típicas
MAX_EVENTS = 8           # como mucho, tantos movimientos por moneda
TREND_DAYS = 20          # cierres usados para la tendencia
TREND_HALFLIFE = 7.0     # días: un cierre de hace 7 días pesa la mitad que el de hoy
TREND_DAMP = 0.8         # amortiguación diaria de la tendencia
NEWS_K = 0.6             # fuerza de la corrección por noticias (en desviaciones típicas diarias)
NEWS_DECAY = 0.6         # cada día la noticia influye un 40 % menos
FNG_HORIZON = 3          # días del efecto del índice de miedo y codicia
RECENT_DAYS = 7
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) CriptoSenales/1.0"

COIN_NAMES = {
    "BTC": ["bitcoin"], "ETH": ["ethereum", "ether"], "SOL": ["solana"],
    "BNB": ["bnb", "binance coin"], "XRP": ["xrp", "ripple"], "ADA": ["cardano"],
    "DOGE": ["dogecoin"], "DOT": ["polkadot"], "AVAX": ["avalanche"], "LINK": ["chainlink"],
    "LTC": ["litecoin"], "TRX": ["tron"], "POL": ["polygon"], "MATIC": ["polygon"],
    "SHIB": ["shiba inu"], "TON": ["toncoin"], "SUI": ["sui network", "sui"],
    "PEPE": ["pepe coin", "pepecoin"], "XLM": ["stellar"], "BCH": ["bitcoin cash"],
    "NEAR": ["near protocol"], "UNI": ["uniswap"], "ATOM": ["cosmos"], "APT": ["aptos"],
}
RSS_FEEDS = [
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Cointelegraph", "https://cointelegraph.com/rss"),
    ("Decrypt", "https://decrypt.co/feed"),
]
FNG_URL = "https://api.alternative.me/fng/?limit=0&format=json"

# ─────────────────────────── TONO DE LOS TITULARES ───────────────────────────
# (expresión, peso). Positivo = alcista, negativo = bajista. Se busca en minúsculas.
_LEX = [
    # inglés, alcista
    (r"all[- ]time highs?|\bath\b|record highs?", 2.0), (r"\bsoar(s|ed|ing)?\b", 2.0),
    (r"\bsurg(e|es|ed|ing)\b", 2.0), (r"\bskyrocket", 2.0), (r"\bmoon(s|ing)?\b", 1.5),
    (r"\brall(y|ies|ied|ying)\b", 1.5), (r"\bjump(s|ed|ing)?\b", 1.5), (r"\bbreakout\b", 1.5),
    (r"\bspik(e|es|ed|ing)\b", 1.0), (r"\bclimb(s|ed|ing)?\b", 1.0), (r"\bgains?\b", 1.0),
    (r"\bris(e|es|ing)\b|\brose\b", 1.0), (r"\brebound(s|ed|ing)?\b", 1.0),
    (r"\brecover(s|ed|ing|y)?\b", 1.0), (r"\bbullish\b|\bbulls?\b", 1.5),
    (r"\binflows?\b", 1.5), (r"\bapprov(al|e|es|ed)\b", 1.5), (r"\badopt(ion|s|ed)?\b", 1.0),
    (r"\bpartnership\b", 0.8), (r"\bupgrade[sd]?\b", 0.8), (r"\blaunch(es|ed)?\b", 0.5),
    (r"\betfs?\b", 0.5), (r"\bbuy(s|ing)?\b|\bbought\b", 0.8), (r"\baccumulat", 1.0),
    (r"strategic reserve|\breserve\b", 1.0), (r"\binstitutional\b", 0.5),
    (r"\boutperform", 1.0), (r"\bboost(s|ed)?\b", 1.0), (r"\boptimis", 1.0),
    (r"\bmilestone\b", 0.8), (r"\bwins?\b|\bvictory\b", 1.0), (r"\bdismiss(ed|es)?\b", 0.8),
    (r"rate cuts?|\bdovish\b", 1.0), (r"\bshort squeeze\b", 1.0), (r"\bgreen\b", 0.5),
    # inglés, bajista
    (r"\bcrash(es|ed|ing)?\b", -2.0), (r"\bplung(e|es|ed|ing)\b", -2.0),
    (r"\bcollaps(e|es|ed|ing)\b", -2.0), (r"\bbankrupt(cy)?\b|\binsolven", -2.0),
    (r"\bhack(s|ed|er|ers)?\b|\bexploit(s|ed)?\b|\bbreach\b|\bstolen\b|\btheft\b", -2.0),
    (r"\bscam\b|\bfraud\b|\bponzi\b", -2.0), (r"\btumbl(e|es|ed|ing)\b", -1.5),
    (r"\bslump(s|ed|ing)?\b", -1.5), (r"\bsink(s|ing)?\b|\bsank\b", -1.5),
    (r"sell[- ]?off|\bdump(s|ed|ing)?\b", -1.5), (r"\bliquidat", -1.5),
    (r"\boutflows?\b", -1.5), (r"\bbearish\b|\bbears?\b", -1.5), (r"\bpanic\b", -1.5),
    (r"\bdrop(s|ped|ping)?\b", -1.0), (r"\bfall(s|ing)?\b|\bfell\b", -1.0),
    (r"\bdeclin(e|es|ed|ing)\b", -1.0), (r"\bslid(e|es|ing)?\b", -1.0), (r"\bdips?\b", -0.8),
    (r"\blosses\b|\bloss\b|\blose[sr]?\b", -1.0), (r"\blawsuit\b|\bsu(es|ed)\b", -1.5),
    (r"\bcharg(es|ed)\b|\bindict", -1.0), (r"\bban(s|ned)?\b|\bcrackdown\b", -1.5),
    (r"\bprobe\b|\binvestigat", -1.0), (r"\breject(s|ed|ion)?\b|\bdenied\b", -1.0),
    (r"\bdela(y|ys|yed)\b|\bpostpon", -0.8), (r"\bfears?\b|\bworr(y|ies|ied)\b", -1.0),
    (r"\bwarn(s|ing|ed)?\b", -0.8), (r"\brisks?\b", -0.5), (r"\brecession\b", -1.0),
    (r"\btariffs?\b", -0.8), (r"rate hikes?|\bhawkish\b", -1.0), (r"\bred\b", -0.5),
    (r"\blows?\b|\blowest\b", -0.8), (r"\bunder pressure\b|\bpressure\b", -0.5),
    (r"\bwithdrawals?\b", -1.0), (r"\bshuts? down\b|\bshutdown\b", -1.0),
    # español, alcista
    (r"\bsub(e|en|ida|idas)\b", 1.0), (r"\bse dispara|\bdispar(a|an)\b", 2.0),
    (r"\brepunt(a|an|e)\b", 1.0), (r"\brécord\b|\bmáximos?\b|máximo histórico", 2.0),
    (r"\balcista\b", 1.5), (r"\baprob(ación|ado|ada|ó)\b", 1.5), (r"\badopción\b", 1.0),
    (r"\bentradas\b", 1.0), (r"\bganancias\b|\bgana\b", 1.0), (r"\brecuper(a|an|ación)\b", 1.0),
    (r"\bimpuls(o|a)\b", 1.0),
    # español, bajista
    (r"\bbajista\b", -1.5), (r"\bca(e|en|ída|ídas)\b", -1.0),
    (r"\bse desploma|\bdesplom(e|a|an)\b|\bse hunde|\bhundimiento\b", -2.0),
    (r"\bpérdidas\b|\bpierde\b", -1.0), (r"\bhackeo\b|\brobo\b|\bestafa\b|\bfraude\b", -2.0),
    (r"\bdemanda\b", -1.0), (r"\bprohib", -1.5), (r"\bquiebra\b", -2.0),
    (r"\bliquidaciones\b", -1.5), (r"\bsalidas\b", -1.0), (r"\bmiedo\b|\bpánico\b", -1.5),
    (r"\bretroce(de|so)\b", -1.0), (r"\bretiradas\b|\bretiros\b", -1.0), (r"\bmínimos?\b", -1.0), (r"venta masiva", -1.5),
]
_LEX = [(re.compile(p), w) for p, w in _LEX]
_NEG = re.compile(r"\b(not|no|fails? to|without|despite|ni|sin)\s+(\w+\s+)?$")


def sentiment(title):
    """Tono de un titular entre -1 (muy bajista) y +1 (muy alcista)."""
    t = title.lower()
    total = 0.0
    for rx, w in _LEX:
        for m in rx.finditer(t):
            # "no surge", "fails to rally"... invierte el sentido
            total += -w if _NEG.search(t[max(0, m.start() - 20):m.start()]) else w
    return math.tanh(total / 2.0)


def _word(sym):
    return re.compile(r"(?<![A-Za-z0-9])" + re.escape(sym) + r"(?![A-Za-z0-9])")


def relevance(title, coin):
    """1 si el titular habla de la moneda; menos si es del mercado cripto en general."""
    low = title.lower()
    names = COIN_NAMES.get(coin, [])
    if _word(coin).search(title) or any(re.search(r"\b" + re.escape(n) + r"\b", low) for n in names):
        return 1.0
    if coin != "BTC" and re.search(r"\bbitcoin\b|\bbtc\b", low):
        return 0.4  # bitcoin arrastra al resto
    if re.search(r"\bcrypto|\bcripto|\bmarket\b|\bmercado\b|\baltcoins?\b|\bstablecoins?\b", low):
        return 0.3
    return 0.0


# ─────────────────────────── DESCARGAS ───────────────────────────

def http_get(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en,es;q=0.8"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


_FEEDS = {}


def feed_get(url, max_age=600):
    """Los RSS generales son iguales para todas las monedas: se descargan una vez cada 10 min."""
    hit = _FEEDS.get(url)
    if hit and time.time() - hit[0] < max_age:
        return hit[1]
    data = http_get(url)
    _FEEDS[url] = (time.time(), data)
    return data


def parse_rss(data, default_source=""):
    items = []
    root = ET.fromstring(data)
    for it in root.iter("item"):
        title = html.unescape((it.findtext("title") or "").strip())
        link = (it.findtext("link") or "").strip()
        src_el = it.find("source")
        source = (src_el.text or "").strip() if src_el is not None and src_el.text else default_source
        if source and title.endswith(" - " + source):  # Google pone " - Medio" al final
            title = title[: -len(source) - 3].strip()
        try:
            t = int(email.utils.parsedate_to_datetime(it.findtext("pubDate")).timestamp() * 1000)
        except Exception:
            continue
        if title:
            items.append({"t": t, "title": title, "source": source, "link": link})
    return items


def google_news(query, lang="en", after=None, before=None, when=None):
    q = query
    if when:
        q += f" when:{when}"
    if after:
        q += f" after:{after}"
    if before:
        q += f" before:{before}"
    loc = {"en": "hl=en-US&gl=US&ceid=US:en", "es": "hl=es&gl=ES&ceid=ES:es"}[lang]
    url = f"https://news.google.com/rss/search?q={urllib.parse.quote(q)}&{loc}"
    return parse_rss(http_get(url), "Google Noticias")


def coin_query(coin):
    names = COIN_NAMES.get(coin)
    if coin == "BTC":
        return "bitcoin"
    return f"{names[0]} crypto" if names else f"{coin} crypto"


_FNG = {"t": 0, "data": None}


def fear_greed():
    """Historial diario del índice de miedo (0) y codicia (100): [(t_ms, valor)] ascendente."""
    if _FNG["data"] is None or time.time() - _FNG["t"] > 3600:
        import json
        d = json.loads(http_get(FNG_URL).decode())
        _FNG["data"] = sorted((int(x["timestamp"]) * 1000, float(x["value"])) for x in d["data"])
        _FNG["t"] = time.time()
    return _FNG["data"]


def _day(t):
    return datetime.fromtimestamp(t / 1000, timezone.utc).strftime("%Y-%m-%d")


def _dedupe(items):
    seen, out = set(), []
    for it in sorted(items, key=lambda x: -x["t"]):
        k = re.sub(r"[^a-z0-9]", "", it["title"].lower())[:70]
        if k and k not in seen:
            seen.add(k)
            out.append(it)
    return out


def _score_items(items, coin):
    out = []
    for it in items:
        rel = relevance(it["title"], coin)
        if rel > 0:
            out.append({**it, "rel": rel, "score": round(sentiment(it["title"]), 3)})
    return out


def recent_news(coin, now_ms, errors):
    """Noticias de los últimos RECENT_DAYS días, con su tono y relevancia."""
    items = []
    for lang in ("en", "es"):
        try:
            q = coin_query(coin) if lang == "en" else (COIN_NAMES.get(coin, [coin.lower()])[0])
            items += google_news(q, lang=lang, when=f"{RECENT_DAYS}d")
        except Exception as e:
            errors.append(f"Google Noticias ({lang}): {e}")
    for name, url in RSS_FEEDS:
        try:
            items += parse_rss(feed_get(url), name)
        except Exception as e:
            errors.append(f"{name}: {e}")
    items = [x for x in items if now_ms - RECENT_DAYS * DAY_MS <= x["t"] <= now_ms + 3600_000]
    return _score_items(_dedupe(items), coin)


# ─────────────────────────── MOVIMIENTOS FUERTES Y SUS NOTICIAS ───────────────────────────

def _stdev(xs):
    if len(xs) < 2:
        return 0.0
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def big_moves(closes, now_ms):
    """Días de los últimos EVENT_LOOKBACK días con variación >= EVENT_SIGMA desv. típicas."""
    rets = [(closes[i][0], closes[i][1] / closes[i - 1][1] - 1) for i in range(1, len(closes))]
    sigma = _stdev([math.log(1 + r) for _, r in rets[-365:]])
    lim = max(EVENT_SIGMA * sigma, 0.03)
    cand = [(t, r) for t, r in rets if t >= now_ms - EVENT_LOOKBACK * DAY_MS and abs(r) >= lim]
    cand.sort(key=lambda x: -abs(x[1]))
    return sorted(cand[:MAX_EVENTS], key=lambda x: -x[0]), sigma


def event_news(coin, t, ret, cache_get, cache_put, now_ms, errors):
    """Noticias publicadas alrededor del día t (vela que abre en t). Se guardan en caché
    para siempre cuando el día ya está lejos (las noticias pasadas no cambian)."""
    key = f"nev:{coin}:{t}"
    cached = cache_get(key)
    if cached is not None:
        return cached
    items, ok = [], True
    try:
        items = google_news(coin_query(coin), "en", after=_day(t - DAY_MS), before=_day(t + 2 * DAY_MS))
    except Exception as e:
        ok = False
        errors.append(f"Google Noticias ({_day(t)}): {e}")
    near = [x for x in items if t - 0.75 * DAY_MS <= x["t"] <= t + 1.25 * DAY_MS]
    items = _score_items(_dedupe(near or items), coin)
    # las más relevantes: que hablen de la moneda, con tono marcado y en la dirección del precio
    sign = 1 if ret > 0 else -1

    def rank(x):
        return x["rel"] * (0.3 + abs(x["score"])) * (1.6 if x["score"] * sign > 0.1 else 1.0)
    items.sort(key=rank, reverse=True)
    if ok and now_ms - t > 3 * DAY_MS:
        cache_put(key, items[:12])
    return items[:12]


def weighted_tone(items, now_ms=None, halflife_days=None):
    num = den = 0.0
    for x in items:
        w = x["rel"]
        if halflife_days and now_ms:
            w *= 0.5 ** (max(0, now_ms - x["t"]) / DAY_MS / halflife_days)
        num += w * x["score"]
        den += w
    return (num / den if den else 0.0), den


# ─────────────────────────── PREDICCIÓN ───────────────────────────

def wls_slope(xs, ys, ws):
    sw = sum(ws)
    mx = sum(w * x for w, x in zip(ws, xs)) / sw
    my = sum(w * y for w, y in zip(ws, ys)) / sw
    sxx = sum(w * (x - mx) ** 2 for w, x in zip(ws, xs))
    sxy = sum(w * (x - mx) * (y - my) for w, x, y in zip(ws, xs, ys))
    return sxy / sxx if sxx else 0.0


def trend_slope(logs):
    """Pendiente (log-precio por día) de los últimos TREND_DAYS valores, ponderados."""
    ys = logs[-TREND_DAYS:]
    n = len(ys)
    xs = list(range(-n + 1, 1))
    ws = [0.5 ** (-x / TREND_HALFLIFE) for x in xs]
    return wls_slope(xs, ys, ws)


def damp_sum(h, phi=TREND_DAMP):
    return sum(phi ** i for i in range(1, h + 1))


def trend_backtest(logs, horizon=3, days=365):
    """Acierto histórico de la dirección de la tendencia a `horizon` días."""
    hit = n = 0
    start = max(TREND_DAYS, len(logs) - days - horizon)
    for i in range(start, len(logs) - horizon):
        b = trend_slope(logs[: i + 1])
        move = logs[i + horizon] - logs[i]
        if abs(b) < 1e-9 or move == 0:
            continue
        n += 1
        hit += (b > 0) == (move > 0)
    return (round(100 * hit / n) if n else None), n


def fng_model(closes, fng):
    """Coeficiente: cuánto se mueve la moneda en FNG_HORIZON días por cada punto que el
    índice sube sobre su media de la semana anterior. Regresión sobre ~2 años."""
    by_day = {t // DAY_MS: v for t, v in fng}
    xs, ys = [], []
    days = [t // DAY_MS for t, _ in closes]
    logs = [math.log(c) for _, c in closes]
    for i in range(max(8, len(closes) - 730), len(closes) - FNG_HORIZON):
        d = days[i]
        prev = [by_day.get(d - k) for k in range(1, 8)]
        if d not in by_day or None in prev:
            continue
        xs.append((by_day[d] - sum(prev) / 7) / 100)
        ys.append(logs[i + FNG_HORIZON] - logs[i])
    if len(xs) < 60:
        return 0.0, 0.0, len(xs)
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if not sxx:
        return 0.0, 0.0, len(xs)
    beta = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    resid = [y - my - beta * (x - mx) for x, y in zip(xs, ys)]
    se = math.sqrt(sum(r * r for r in resid) / (len(xs) - 2) / sxx)
    tstat = beta / se if se else 0.0
    return beta, tstat, len(xs)


def forecast(closes, price_now, now_ms, news_signal, news_weight, fng):
    """Predicción para los próximos PRED_DAYS días.
    closes: [(t, cierre)] de velas cerradas, ascendente.  price_now: precio actual."""
    logs = [math.log(c) for _, c in closes]
    sigma = _stdev([logs[i] - logs[i - 1] for i in range(max(1, len(logs) - 90), len(logs))])
    slope = trend_slope(logs)
    lp0 = math.log(price_now)

    # índice de miedo y codicia: cambio frente a la media de la semana anterior
    fng_info, fng_eff = None, 0.0
    if fng:
        beta, tstat, n = fng_model(closes, fng)
        last = fng[-1][1]
        prev = [v for _, v in fng[-8:-1]]
        delta = last - (sum(prev) / len(prev) if prev else last)
        shrink = min(1.0, abs(tstat) / 2.0)  # si el coeficiente no es fiable, cuenta menos
        fng_eff = beta * shrink * delta / 100
        fng_info = {"value": last, "delta": delta, "beta": beta, "t": tstat, "n": n,
                    "shrink": shrink}

    days = []
    for h in range(1, PRED_DAYS + 1):
        base = slope * damp_sum(h)
        news = NEWS_K * news_signal * news_weight * sigma * sum(NEWS_DECAY ** (i - 1) for i in range(1, h + 1))
        mood = fng_eff * min(h, FNG_HORIZON) / FNG_HORIZON
        corr = news + mood
        cap = 2 * sigma * math.sqrt(h)
        corr = max(-cap, min(cap, corr))
        lp = lp0 + base + corr
        band = sigma * math.sqrt(h)
        days.append({"t": now_ms + h * DAY_MS, "base": math.exp(lp0 + base), "pred": math.exp(lp),
                     "lo": math.exp(lp - band), "hi": math.exp(lp + band),
                     "base_pct": math.exp(base) - 1, "news_pct": math.exp(news) - 1,
                     "mood_pct": math.exp(mood) - 1, "pct": math.exp(lp - lp0) - 1})
    hit, n = trend_backtest(logs)
    return {"days": days, "sigma": sigma, "slope": slope, "trend_hit": hit, "trend_n": n,
            "fng": fng_info}


# ─────────────────────────── TODO JUNTO ───────────────────────────

def build(coin, closes, price_now, now_ms, cache_get, cache_put):
    """Descarga y calcula todo lo que muestra el panel de noticias de una moneda."""
    errors = []
    recent = recent_news(coin, now_ms, errors)
    tone48, w48 = weighted_tone([x for x in recent if now_ms - x["t"] <= 2 * DAY_MS], now_ms, 1.0)
    tone7, w7 = weighted_tone(recent)
    signal = max(-1.0, min(1.0, tone48 + 0.5 * (tone48 - tone7))) if w48 else 0.5 * tone7

    moves, _ = big_moves(closes, now_ms)
    events, coherent, judged = [], 0, 0
    for t, ret in moves:
        items = event_news(coin, t, ret, cache_get, cache_put, now_ms, errors)
        tone, w = weighted_tone(items[:6])
        verdict = None
        if w and abs(tone) >= 0.1:
            judged += 1
            verdict = (tone > 0) == (ret > 0)
            coherent += verdict
        events.append({"t": t, "ret": ret, "items": items[:3], "tone": tone, "agree": verdict})
        time.sleep(0.2)  # sin agobiar a Google
    # fiabilidad de las noticias para esta moneda (con un ajuste para pocos casos)
    rel = (coherent + 1) / (judged + 2)
    weight = max(0.25, min(1.0, 2 * rel - 1)) if judged else 0.25

    fng = None
    try:
        fng = fear_greed()
    except Exception as e:
        errors.append(f"Índice de miedo y codicia: {e}")
    fc = forecast(closes, price_now, now_ms, signal, weight, fng)

    recent.sort(key=lambda x: (-(x["rel"] * (0.4 + abs(x["score"]))), -x["t"]))
    return {
        "coin": coin, "time": now_ms, "recent": recent[:25], "n_recent": len(recent),
        "tone48": tone48, "tone7": tone7, "signal": signal, "n48": w48,
        "events": events, "coherent": coherent, "judged": judged, "news_weight": weight,
        "forecast": fc, "price": price_now, "history": closes[-45:], "errors": errors,
    }
