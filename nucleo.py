"""
Núcleo de Cripto Señales para Android (sin interfaz)
Autor: Luis Tranche Casado

Las funciones de datos, indicadores, tu compra y semáforo están copiadas tal cual del
programa de escritorio (CriptoSenales.py), para que los cálculos sean idénticos.
Al final, la clase Nucleo coordina en segundo plano lo que en el escritorio hacen las
ventanas: descargar precios, calcular señales, aprender (IA), buscar noticias y predecir.
"""

import bisect
import json
import math
import os
import queue
import sqlite3
import sys
import threading
import time
import traceback
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import aprendizaje
import noticias

# ─────────────────────────── CONFIGURACIÓN ───────────────────────────
DEFAULT_COINS = "BTC, ETH, SOL, BNB, XRP, ADA, DOGE"


QUOTE = "USDT"


REFRESH_MIN = 15


HISTORY_DAYS = 1500


BUY_IN, BUY_OUT = 40, 10


SELL_IN, SELL_OUT = -40, -10


EVAL_DAYS = 30


MIN_PROFIT = 0.03


API_HOSTS = ["https://api.binance.com", "https://data-api.binance.vision"]


DAY_MS = 86_400_000


BUY, SELL, WAIT = "COMPRAR", "VENDER", "ESPERAR"


def http_json(path):
    last = None
    for host in API_HOSTS:
        try:
            req = urllib.request.Request(host + path, headers={"User-Agent": "CriptoSenales/1.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode())
        except Exception as e:  # prueba el siguiente servidor
            last = e
    raise last


class Store:
    """Velas diarias en SQLite, en la carpeta de datos del usuario."""

    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS candles (symbol TEXT, t INTEGER, o REAL, h REAL, l REAL,
                c REAL, v REAL, PRIMARY KEY (symbol, t));
            CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
        """)
        self.lock = threading.Lock()

    def last_t(self, symbol):
        with self.lock:
            r = self.db.execute("SELECT MAX(t) FROM candles WHERE symbol=?", (symbol,)).fetchone()
        return r[0]

    def save(self, symbol, rows):
        with self.lock:
            self.db.executemany("INSERT OR REPLACE INTO candles VALUES (?,?,?,?,?,?,?)",
                                [(symbol, int(k[0]), float(k[1]), float(k[2]), float(k[3]),
                                  float(k[4]), float(k[5])) for k in rows])
            self.db.commit()

    def candles(self, symbol):
        with self.lock:
            return self.db.execute("SELECT t, o, h, l, c, v FROM candles WHERE symbol=? ORDER BY t",
                                   (symbol,)).fetchall()

    def get(self, k, default=None):
        with self.lock:
            r = self.db.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
        return json.loads(r[0]) if r else default

    def put(self, k, v):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (k, json.dumps(v)))
            self.db.commit()


def update_symbol(store, symbol, now_ms):
    """Descarga las velas que falten (desde la última guardada, que se vuelve a pedir
    porque pudo guardarse sin cerrar)."""
    last = store.last_t(symbol)
    start = last if last is not None else now_ms - HISTORY_DAYS * DAY_MS
    while True:
        rows = http_json(f"/api/v3/klines?symbol={symbol}&interval=1d&startTime={start}&limit=1000")
        if not rows:
            break
        store.save(symbol, rows)
        if len(rows) < 1000:
            break
        start = int(rows[-1][0]) + DAY_MS


def sma(xs, n):
    out, s = [None] * len(xs), 0.0
    for i, x in enumerate(xs):
        s += x
        if i >= n:
            s -= xs[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def ema(xs, n):
    out, k, e = [None] * len(xs), 2 / (n + 1), None
    for i, x in enumerate(xs):
        if x is None:
            continue
        e = x if e is None else x * k + e * (1 - k)
        out[i] = e
    return out


def rsi(closes, n=14):
    out = [None] * len(closes)
    gain = loss = 0.0
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        g, l = max(d, 0), max(-d, 0)
        if i <= n:
            gain += g / n
            loss += l / n
        else:
            gain = (gain * (n - 1) + g) / n
            loss = (loss * (n - 1) + l) / n
        if i >= n:
            out[i] = 100.0 if loss == 0 else 100 - 100 / (1 + gain / loss)
    return out


def stdev(xs, n, means):
    out = [None] * len(xs)
    for i in range(n - 1, len(xs)):
        m = means[i]
        out[i] = (sum((x - m) ** 2 for x in xs[i - n + 1:i + 1]) / n) ** 0.5
    return out


def analyze(candles):
    """Devuelve por cada día: (t, cierre, puntuación, estado, motivos)."""
    t = [c[0] for c in candles]
    close = [c[4] for c in candles]
    vol = [c[5] for c in candles]
    n = len(close)
    if n < 210:
        return []

    sma200, ema50, ema200 = sma(close, 200), ema(close, 50), ema(close, 200)
    e12, e26 = ema(close, 12), ema(close, 26)
    macd = [a - b for a, b in zip(e12, e26)]
    sig = ema(macd, 9)
    hist = [m - s for m, s in zip(macd, sig)]
    r = rsi(close)
    mid = sma(close, 20)
    sd = stdev(close, 20, mid)
    obv = [0.0]
    for i in range(1, n):
        obv.append(obv[-1] + (vol[i] if close[i] > close[i - 1] else -vol[i] if close[i] < close[i - 1] else 0))
    obv20 = sma(obv, 20)

    rows, state = [], WAIT
    for i in range(200, n):
        parts = []
        # Tendencia (peso 2 cada una)
        parts.append((2 if close[i] > sma200[i] else -2,
                      "precio sobre media 200" if close[i] > sma200[i] else "precio bajo media 200"))
        parts.append((2 if ema50[i] > ema200[i] else -2,
                      "media 50 sobre 200" if ema50[i] > ema200[i] else "media 50 bajo 200"))
        # Impulso
        if hist[i] > 0 and hist[i] > hist[i - 1]:
            parts.append((1.5, "MACD subiendo"))
        elif hist[i] < 0 and hist[i] < hist[i - 1]:
            parts.append((-1.5, "MACD bajando"))
        else:
            parts.append((0.75 if hist[i] > 0 else -0.75, "MACD perdiendo fuerza"))
        if r[i] < 30:
            parts.append((1.5, f"RSI {r[i]:.0f} sobrevendido"))
        elif r[i] > 70:
            parts.append((-1.5, f"RSI {r[i]:.0f} sobrecomprado"))
        else:
            parts.append(((r[i] - 50) / 20 * 0.75, f"RSI {r[i]:.0f}"))
        # Extremos (Bollinger %B)
        pb = 0.5 if sd[i] == 0 else (close[i] - (mid[i] - 2 * sd[i])) / (4 * sd[i])
        if pb < 0:
            parts.append((1, "bajo la banda de Bollinger"))
        elif pb > 1:
            parts.append((-1, "sobre la banda de Bollinger"))
        # Volumen
        parts.append((1 if obv[i] > obv20[i] else -1,
                      "volumen comprador" if obv[i] > obv20[i] else "volumen vendedor"))

        max_abs = 2 + 2 + 1.5 + 1.5 + 1 + 1
        score = round(sum(p for p, _ in parts) / max_abs * 100)

        if state == BUY and score < BUY_OUT:
            state = WAIT
        elif state == SELL and score > SELL_OUT:
            state = WAIT
        if state == WAIT:
            if score >= BUY_IN:
                state = BUY
            elif score <= SELL_IN:
                state = SELL
        reasons = [txt for p, txt in sorted(parts, key=lambda x: -abs(x[0]))[:4]]
        rows.append((t[i], close[i], score, state, reasons))
    return rows


def hit_rate(rows):
    """Acierto histórico: % de señales que acertaron la dirección a EVAL_DAYS días."""
    hits = total = 0
    for k in range(1, len(rows)):
        st, prev = rows[k][3], rows[k - 1][3]
        if st == prev or st == WAIT or k + EVAL_DAYS >= len(rows):
            continue
        ret = rows[k + EVAL_DAYS][1] / rows[k][1] - 1
        total += 1
        hits += (ret > 0) if st == BUY else (ret < 0)
    return (round(100 * hits / total), total) if total else (None, 0)


def median(xs):
    xs = sorted(xs)
    n = len(xs)
    return None if not n else (xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2)


MIN_CYCLES = 2


def estimate_dates(transitions, state, now_ms, bought_t=None):
    """Fechas probables de la próxima señal de COMPRA y de VENTA, según cuánto han durado
    en el pasado los ciclos de esa moneda:
      compra → venta: días desde que entra COMPRAR hasta que entra VENDER
      venta → compra: días desde que entra VENDER hasta que entra COMPRAR
    Si se indica bought_t (fecha en que el usuario compró la moneda) y desde entonces no ha
    habido señal de VENDER, el ciclo se cuenta desde esa compra: la venta se estima desde
    la fecha de compra y la recompra desde esa venta.
    Cada fecha puede ser: t (ms), "now" o None."""
    entries = [(t, st) for t, st in transitions if st in (BUY, SELL)]
    d_bs, d_sb = [], []
    for k, (t, st) in enumerate(entries):
        nxt = next((t2 for t2, st2 in entries[k + 1:] if st2 != st), None)
        if nxt is not None:
            (d_bs if st == BUY else d_sb).append(nxt - t)
    m_bs = median(d_bs) if len(d_bs) >= MIN_CYCLES else None
    m_sb = median(d_sb) if len(d_sb) >= MIN_CYCLES else None
    info = (f"Ciclos de esta moneda: compra→venta {len(d_bs)} (mediana "
            f"{'—' if m_bs is None else round(m_bs / DAY_MS)} días), venta→compra {len(d_sb)} "
            f"(mediana {'—' if m_sb is None else round(m_sb / DAY_MS)} días)")
    last = entries[-1] if entries else None
    buy = sell = None
    if (bought_t is not None and state != SELL
            and not any(st == SELL and t >= bought_t for t, st in entries)):
        # tienes la moneda y aún no ha habido señal de venta: el ciclo empieza en tu compra
        sell = bought_t + m_bs if m_bs is not None else None
        buy = sell + m_sb if sell is not None and m_sb is not None else None
        return {"buy": buy, "sell": sell, "info": info}
    if state == BUY:
        buy = "now"
        sell = last[0] + m_bs if last and m_bs is not None else None
    elif state == SELL:
        sell = "now"
        buy = last[0] + m_sb if last and m_sb is not None else None
    elif last:  # ESPERAR: se continúa el ciclo desde la última señal
        if last[1] == BUY:
            sell = last[0] + m_bs if m_bs is not None else None
            buy = sell + m_sb if sell is not None and m_sb is not None else None
        else:
            buy = last[0] + m_sb if m_sb is not None else None
            sell = buy + m_bs if buy is not None and m_bs is not None else None
    return {"buy": buy, "sell": sell, "info": info}


def pct(x):
    return f"{x:+.1%}".replace(".", ",")


def holding_view(r, bought_t, p0, est, now_ms):
    """Qué hacer con una moneda que ya tienes, teniendo en cuenta a cuánto la compraste.
    Devuelve (texto de la celda "Venta prob.", tipo, líneas para la información emergente).
    tipo: "profit" (vender ahora deja beneficio), "loss" (señal de venta pero sin
    beneficio suficiente), "missed" (ya pasó una venta con beneficio) o "wait"."""
    price, state = r["price"], r["state"]
    target = p0 * (1 + MIN_PROFIT)
    gain = price / p0 - 1
    lines = [f"Compra a {fmt_price(p0)} $ → ahora {fmt_price(price)} $ ({pct(gain)})",
             f"Precio mínimo para ganar al menos un {MIN_PROFIT:.0%}: {fmt_price(target)} $"]

    since = [(t, c) for t, c in r["closes"] if t >= bought_t]
    if since:
        t_max, c_max = max(since, key=lambda x: x[1])
        lines.append(f"Mejor cierre desde tu compra: {fmt_price(c_max)} $ el {fmt_date(t_max)} "
                     f"({pct(c_max / p0 - 1)})")
    sells = [(t, close_on(r["closes"], t)) for t, st in r["transitions"]
             if st == SELL and t >= bought_t]
    sells = [(t, c) for t, c in sells if c]
    for t, c in sells:
        lines.append(f"Señal VENDER el {fmt_date(t)} a {fmt_price(c)} $ ({pct(c / p0 - 1)})")
    good_past = [(t, c) for t, c in sells if c >= target]

    next_sell = fmt_est(est["sell"], now_ms)
    if state == SELL:
        if price >= target:
            lines.append(f"El indicador dice VENDER y ahora mismo venderías con beneficio ({pct(gain)}).")
            return f"AHORA {pct(gain)}", "profit", lines
        lines.append(f"El indicador dice VENDER, pero estás por debajo del objetivo "
                     f"({pct(gain)}): venderías con pérdida o sin margen.")
        return f"AHORA {pct(gain)} ✗", "loss", lines

    if good_past:
        t, c = good_past[-1]
        lines.append(f"Ya pasó una señal de VENDER con beneficio ({fmt_date(t)}, {pct(c / p0 - 1)}). "
                     f"Próxima venta probable: {next_sell}")
        if price < target:
            lines[-1] += f", y el precio tendría que volver a {fmt_price(target)} $ para ganar"
        return f"ya pasó {fmt_date(t)} {pct(c / p0 - 1)}", "missed", lines

    if price >= target:
        lines.append(f"Ya estás en beneficio ({pct(gain)}); la señal de VENDER se espera para {next_sell}.")
        return next_sell, "wait", lines
    lines.append(f"Ahora estás en {pct(gain)}: hace falta que suba a {fmt_price(target)} $ "
                 f"({pct(target / price - 1)}) para vender con beneficio.")
    cell = next_sell if next_sell == "—" else f"{next_sell} · ≥{fmt_price(target)}"
    return cell, "wait", lines


def summarize(symbol, candles, now_ms):
    closed = [c for c in candles if c[0] + DAY_MS <= now_ms]  # solo velas cerradas
    rows = analyze(closed)
    if not rows:
        return None
    t, close, score, state, reasons = rows[-1]
    since = len(rows) - 1
    while since > 0 and rows[since - 1][3] == state:
        since -= 1
    price = candles[-1][4]  # vela de hoy (sin cerrar) = precio actual
    hr, n = hit_rate(rows)
    transitions = [(rows[k][0], rows[k][3]) for k in range(1, len(rows)) if rows[k][3] != rows[k - 1][3]]
    return {
        "symbol": symbol, "price": price, "state": state, "score": score, "reasons": reasons,
        "since_t": rows[since][0], "since_price": rows[since][1],
        "hit": hr, "hit_n": n, "transitions": transitions,
        "closes": [(c[0], c[4]) for c in closed],   # para el precio del día de compra
        "scores": [(x[0], x[2]) for x in rows],      # puntuación de cada día (para la IA)
    }


def close_on(closes, t):
    """Cierre del día t (o del primer día disponible después). None si no hay datos."""
    i = bisect.bisect_left(closes, (t,))
    return closes[i][1] if i < len(closes) else None


def parse_date(text):
    """'dd/mm/aa', 'dd/mm/aaaa', 'dd-mm-aaaa' o 'aaaa-mm-dd' → ms a las 00:00 UTC de ese día."""
    text = text.strip()
    for f in ("%d/%m/%y", "%d/%m/%Y", "%d-%m-%y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d"):
        try:
            d = datetime.strptime(text, f)
        except ValueError:
            continue
        return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000)
    return None


def parse_price(text):
    """Acepta '62.000', '62000', '62.000,50', '62000.5', '0,4512', '0.4512'. None si no vale."""
    s = text.replace("$", "").replace(" ", "").strip()
    if not s:
        return None
    if "," in s and "." in s:          # el último separador es el decimal
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:                     # coma decimal (estilo español)
        s = s.replace(",", ".")
    elif s.count(".") > 1 or (s.count(".") == 1 and len(s.split(".")[1]) == 3
                              and s.split(".")[0] not in ("", "0")):
        s = s.replace(".", "")         # puntos de miles: 62.000 / 1.250.000
    try:
        v = float(s)
    except ValueError:
        return None
    return v if v > 0 else None


COLORS = {BUY: "#2ecc71", SELL: "#ff5c5c", WAIT: "#8fa0b5"}


BUY_DATE_COLOR, SELL_DATE_COLOR = "#ff5c5c", "#2ecc71"


HOLD_COLORS = {"profit": "#2ecc71", "loss": "#f0a030", "missed": "#f0a030", "wait": "#2ecc71"}


GAIN_UP, GAIN_DOWN, MUTED = "#2ecc71", "#ff5c5c", "#8fa0b5"


def fmt_est(v, now_ms):
    if v == "now":
        return "AHORA"
    if v is None:
        return "—"
    if v <= now_ms:
        return "en cualquier momento"  # ya ha pasado lo que suele durar el ciclo
    return fmt_date(v)


def fmt_price(p):
    if p >= 100:
        s = f"{p:,.0f}"
    elif p >= 1:
        s = f"{p:,.2f}"
    else:
        s = f"{p:,.4f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_date(t):
    return datetime.fromtimestamp(t / 1000, timezone.utc).strftime("%d/%m/%y")


NEWS_CACHE_MIN = 20


SEMAFORO_Z = 0.25


# (texto, color de las letras y del borde, fondo del mismo tono)
LIGHTS = {"buy": ("COMPRA", "#2ecc71", "#12301f"), "caution": ("PRECAUCIÓN", "#f0a030", "#352812"),
          "sell": ("VENDE", "#ff5c5c", "#3a1517")}


def traffic_light(res):
    """Semáforo a partir de la predicción final (IA + fórmula con noticias).
    Devuelve (tipo, motivo, texto de ayuda)."""
    fc = res["forecast"]
    d = fc["days"][-1]
    n = len(fc["days"])
    s_n = fc["sigma"] * math.sqrt(n)              # lo que suele moverse en n días
    lim = math.exp(SEMAFORO_Z * s_n) - 1
    z = math.log(1 + d["pct"]) / s_n if s_n else 0.0
    ai, f = d.get("ai_pct"), d.get("formula_pct", d["pct"])
    clash = (ai is not None and ai * f < 0
             and min(abs(math.log(1 + ai)), abs(math.log(1 + f))) > SEMAFORO_Z * s_n)
    if clash:
        kind, why = "caution", "la IA y la fórmula de noticias apuntan en sentidos contrarios"
    elif z >= SEMAFORO_Z:
        kind, why = "buy", f"se espera una subida clara (más de {pct(lim)} en {n} días)"
    elif z <= -SEMAFORO_Z:
        kind, why = "sell", f"se espera una bajada clara (más de {pct(-lim)} en {n} días)"
    else:
        kind, why = "caution", (f"el movimiento previsto es pequeño frente a lo que suele moverse "
                                f"(menos de ±{pct(lim)[1:]} en {n} días)")
    tip = [f"Semáforo: {LIGHTS[kind][0]} — {why}.",
           f"Predicción final a {n} días: {pct(d['pct'])} ({fmt_price(d['pred'])} $), "
           f"rango probable {fmt_price(d['lo'])} – {fmt_price(d['hi'])} $"]
    if ai is not None:
        tip.append(f"IA {pct(ai)} (pesa {d['w_ai']:.0%}) · fórmula con noticias {pct(f)}")
    tip.append(f"Verde si sube más de {pct(lim)}, rojo si baja más de {pct(-lim)}, naranja en medio "
               f"o si IA y fórmula se contradicen.")
    tip.append(f"Calculado a las {datetime.fromtimestamp(res['time'] / 1000):%H:%M}. "
               "Orientativo: no es asesoramiento financiero.")
    return kind, why, "\n".join(tip)


def tone_word(x):
    if x >= 0.35:
        return "muy positivo"
    if x >= 0.12:
        return "positivo"
    if x <= -0.35:
        return "muy negativo"
    if x <= -0.12:
        return "negativo"
    return "neutro"


def tone_color(x):
    return GAIN_UP if x >= 0.12 else GAIN_DOWN if x <= -0.12 else MUTED


# ─────────────────────────── COORDINADOR (sin interfaz) ───────────────────────────

def plain(text):
    """Cambia los símbolos que la fuente de Android puede no tener por equivalentes seguros."""
    for a, b in (("✗", "(!)"), ("✓", "OK"), ("≥", ">="), ("≈", "~"), ("●", ""), ("▲", "+"),
                 ("▼", "-"), ("→", "->"), ("↑", "(+)"), ("↓", "(-)"), ("−", "-"), ("…", "...")):
        text = text.replace(a, b)
    return text


class Nucleo:
    """Hace todo el trabajo en un hilo aparte y avisa con on_change(evento, moneda).
    Eventos: "prices" (tabla nueva), "news" (noticias/predicción/semáforo de una moneda),
    "status" (texto de estado). on_change se llama desde el hilo de trabajo: la interfaz
    debe pasarlo a su propio hilo (en Kivy, con Clock.schedule_once)."""

    def __init__(self, data_dir, on_change):
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        self.store = Store(Path(data_dir) / "datos.sqlite")
        aprendizaje.init(self.store)
        self.on_change = on_change
        default = [c.strip() for c in DEFAULT_COINS.split(",")]
        self.coins = self.store.get("app:coins", default)
        self.bought = self.store.get("app:bought", {})
        self.bought_price = self.store.get("app:bought_price", {})
        self.results, self.news, self.errors = {}, {}, []
        self.status = "Descargando datos..."
        self.last_prices = 0
        self._cv = threading.Condition()
        self._want_prices = False
        self._pending, self._forced = [], set()
        self.working = None   # moneda cuyas noticias se están buscando
        threading.Thread(target=self._loop, daemon=True).start()

    # ── peticiones desde la interfaz
    def refresh(self):
        with self._cv:
            self._want_prices = True
            self._cv.notify()

    def refresh_news(self, coin, force=False, front=True):
        with self._cv:
            if coin in self._pending:
                self._pending.remove(coin)
            if force:
                self._forced.add(coin)
            if front:
                self._pending.insert(0, coin)
            else:
                self._pending.append(coin)
            self._cv.notify()

    def is_fresh(self, coin):
        r = self.news.get(coin)
        return bool(r) and time.time() * 1000 - r["time"] < NEWS_CACHE_MIN * 60_000

    def set_coins(self, text):
        coins = [c.strip().upper() for c in text.replace(";", ",").split(",") if c.strip()]
        if coins:
            self.coins = coins
            self.store.put("app:coins", coins)
            self.refresh()
        return coins

    def bought_t(self, coin):
        s = self.bought.get(coin)
        return parse_date(s) if s else None

    def set_bought(self, coin, date_text, price_text):
        """Guarda tu compra. Devuelve un mensaje para mostrar."""
        date_text, price_text = date_text.strip(), price_text.strip()
        if not date_text:
            self.bought.pop(coin, None)
            self.bought_price.pop(coin, None)
            msg = f"{coin}: compra borrada"
        else:
            t = parse_date(date_text)
            if t is None:
                return f"Fecha no válida «{date_text}» (usa dd/mm/aa)"
            if t > int(time.time() * 1000):
                return "La fecha de compra no puede ser futura"
            self.bought[coin] = datetime.fromtimestamp(t / 1000, timezone.utc).strftime("%Y-%m-%d")
            msg = f"{coin}: comprada el {fmt_date(t)}"
            if price_text:
                p = parse_price(price_text)
                if p is None:
                    return f"Precio no válido «{price_text}» (p. ej. 62.000 o 0,4512)"
                self.bought_price[coin] = p
                msg += f" a {fmt_price(p)} $"
                r = self.results.get(coin)
                ref = close_on(r["closes"], t) if r else None
                if ref and not 0.5 < p / ref < 2:
                    msg += f". Ojo: ese día cotizaba a unos {fmt_price(ref)} $; revisa el número"
            else:
                self.bought_price.pop(coin, None)
                msg += " (precio: cierre de ese día)"
        self.store.put("app:bought", self.bought)
        self.store.put("app:bought_price", self.bought_price)
        return msg

    # ── datos para mostrar
    def row(self, coin):
        """Lo que la lista de monedas muestra de una moneda (o None si aún no hay datos)."""
        r = self.results.get(coin)
        if not r:
            return None
        now_ms = int(time.time() * 1000)
        bt = self.bought_t(coin)
        est = estimate_dates(r["transitions"], r["state"], now_ms, bt)
        out = {"coin": coin, "price": fmt_price(r["price"]), "state": r["state"], "score": r["score"],
               "since": fmt_date(r["since_t"]), "delta": pct(r["price"] / r["since_price"] - 1),
               "hit": "-" if r["hit"] is None else f"{r['hit']}% ({r['hit_n']})",
               "buy": plain(fmt_est(est["buy"], now_ms)), "sell": plain(fmt_est(est["sell"], now_ms)),
               "sell_kind": None, "gain": None, "bought": None, "position": [], "reasons": r["reasons"],
               "est_info": est["info"]}
        if bt is not None:
            user = coin in self.bought_price
            p0 = self.bought_price[coin] if user else close_on(r["closes"], bt)
            out["bought"] = fmt_date(bt) + ("" if user else " (precio ~cierre)")
            if p0:
                out["gain"] = r["price"] / p0 - 1
                out["p0"] = fmt_price(p0)
                txt, kind, lines = holding_view(r, bt, p0, est, now_ms)
                out["sell"], out["sell_kind"] = plain(txt), kind
                out["position"] = [plain(x) for x in lines]
        res = self.news.get(coin)
        if res:
            kind, why, tip = traffic_light(res)
            out["light"], out["light_why"], out["light_tip"] = kind, plain(why), plain(tip)
        else:
            out["light"] = None
        return out

    # ── trabajo en segundo plano
    def _say(self, ev, coin=None):
        try:
            self.on_change(ev, coin)
        except Exception:
            traceback.print_exc()

    def _loop(self):
        while True:
            with self._cv:
                while not self._want_prices and not self._pending:
                    self._cv.wait(timeout=60)
                prices = self._want_prices
                self._want_prices = False
                coin = None if prices else self._pending.pop(0)
                forced = coin in self._forced
                self._forced.discard(coin)
            try:
                if prices:
                    self._do_prices()
                elif forced or not self.is_fresh(coin):
                    self._do_news(coin)
            except Exception:
                traceback.print_exc()

    def _do_prices(self):
        self.status = "Actualizando precios..."
        self._say("status")
        now_ms = int(time.time() * 1000)
        errors, results = [], {}
        for coin in list(self.coins):
            symbol = coin + QUOTE
            try:
                update_symbol(self.store, symbol, now_ms)
            except Exception as e:
                errors.append(f"{coin}: {e}")
            s = summarize(coin, self.store.candles(symbol), now_ms)
            if s:
                results[coin] = s
            elif not any(e.startswith(coin + ":") for e in errors):
                errors.append(f"{coin}: historial insuficiente o par {symbol} inexistente")
        fng = None
        try:
            fng = noticias.fear_greed()
        except Exception:
            pass
        for coin, s in results.items():   # la IA aprende de los días cerrados
            try:
                aprendizaje.learn(self.store, coin, s["closes"], s["scores"], fng)
            except Exception:
                traceback.print_exc()
        self.results, self.errors = results, errors
        self.last_prices = time.time()
        self.status = f"Actualizado {datetime.now():%H:%M}" + (f" · {errors[0]}" if errors else "")
        self._say("prices")
        with self._cv:   # noticias y semáforo de todas las monedas, al final de la cola
            for c in self.coins:
                if c in results and c not in self._pending and not self.is_fresh(c):
                    self._pending.append(c)
            self._cv.notify()

    def _do_news(self, coin):
        r = self.results.get(coin)
        if not r:
            return
        self.working = coin
        self._say("status", coin)
        res = None
        try:
            res = noticias.build(coin, r["closes"], r["price"], int(time.time() * 1000),
                                 self.store.get, self.store.put)
            try:
                aprendizaje.predict(self.store, coin, r, res)
            except Exception:
                traceback.print_exc()
                res["errors"].append("IA: no se ha podido calcular")
        except Exception:
            traceback.print_exc()
        self.working = None
        if res:
            self.news[coin] = res
        self._say("news", coin)
