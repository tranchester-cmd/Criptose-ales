"""
Módulo de IA de CriptoSenales: aprende de sus propias predicciones
Autor: Luis Tranche Casado

Modelo: regresión lineal con aprendizaje en línea por mínimos cuadrados recursivos (RLS)
con factor de olvido. Cada dato nuevo corrige los pesos al momento, sin rehacer todo, y lo
reciente cuenta algo más que lo antiguo (el mercado cambia). Hay un modelo por moneda y por
horizonte (1 a PRED_DAYS + 1 días).

Qué mira (características de cada día):
  tendencia          lo que da la tendencia de los últimos 20 días prolongada h días
  noticias           tono y evolución de las noticias (solo en las predicciones en vivo)
  cambio miedo/cod.  cambio del índice de miedo y codicia frente a la semana anterior
  nivel miedo/cod.   el índice en sí (miedo extremo ... codicia extrema)
  puntuación técnica la puntuación de -100 a +100 de la tabla
  variación 7 d      cuánto se ha movido la moneda en la última semana
  volatilidad        desviación típica diaria de los últimos 90 días
Qué predice: la variación (logarítmica) entre el cierre de un día y el de h días después.

Cómo aprende:
  1. La primera vez, recorre ~2 años de historial día a día, como si los viviera:
     predice, mira lo que pasó y corrige. Así empieza con experiencia.
  2. Cada día que cierra es un dato nuevo.
  3. Cada predicción que muestra el panel se guarda con todo lo que sabía (también las
     noticias). Cuando llega el precio real se evalúa y el modelo aprende de su error.
     Así aprende cuánto pesan de verdad las noticias para cada moneda.
  4. Lleva la cuenta de su error, el de la fórmula y el de "no cambia nada". La predicción
     final mezcla IA y fórmula según cuál está acertando más últimamente.

Todo se guarda en la base de datos de CriptoSenales: el aprendizaje continúa entre sesiones.
No usa Qt ni librerías externas.
"""

import json
import math
import threading
import time

import noticias

DAY_MS = 86_400_000
VERSION = 1
H_MAX = noticias.PRED_DAYS + 1      # horizontes 1..H_MAX (ver predict)
BACKFILL_DAYS = 730                 # historial que se recorre la primera vez
LAMBDA = 0.998                      # olvido: un dato de hace ~350 días pesa la mitad
P0 = 10.0                           # incertidumbre inicial de los pesos
ALPHA = 0.02                        # suavizado de los errores medios (≈ últimos 50 casos)
FEATURES = ["sesgo", "tendencia", "noticias", "cambio miedo/codicia", "nivel miedo/codicia",
            "puntuación técnica", "variación 7 d", "volatilidad"]
K = len(FEATURES)

_lock = threading.Lock()


# ─────────────────────────── ÁLGEBRA (RLS) ───────────────────────────

def new_model():
    return {"w": [0.0] * K, "P": [[P0 if i == j else 0.0 for j in range(K)] for i in range(K)],
            "n": 0, "n_live": 0, "e_ai": None, "e_f": None, "e_0": None,
            "hit": 0, "hit_n": 0, "last_d": None,
            "fm": [0.0] * K, "fv": [0.0] * K}


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def rls_predict(m, x):
    return dot(m["w"], x)


def rls_update(m, x, y):
    P = m["P"]
    Px = [dot(row, x) for row in P]
    den = LAMBDA + dot(x, Px)
    if den <= 1e-12:
        return
    k = [v / den for v in Px]
    e = y - dot(m["w"], x)
    m["w"] = [w + ki * e for w, ki in zip(m["w"], k)]
    m["P"] = [[(P[i][j] - k[i] * Px[j]) / LAMBDA for j in range(K)] for i in range(K)]
    # simetría y tope, para que no se degrade con miles de pasos
    for i in range(K):
        for j in range(i + 1, K):
            v = 0.5 * (m["P"][i][j] + m["P"][j][i])
            m["P"][i][j] = m["P"][j][i] = v
        m["P"][i][i] = min(max(m["P"][i][i], 1e-9), 1e6)


def ema(old, new):
    return new if old is None else (1 - ALPHA) * old + ALPHA * new


# ─────────────────────────── CARACTERÍSTICAS ───────────────────────────

def make_x(h, slope, news_term, fng_delta, fng_level, score, ret7, sigma):
    return [1.0, slope * noticias.damp_sum(h), news_term, fng_delta / 100, (fng_level - 50) / 50,
            score / 100, ret7, sigma]


def news_term(signal, weight, sigma, h):
    """Lo mismo que usa la fórmula para las noticias, sin su coeficiente (lo aprende la IA)."""
    return signal * weight * sigma * sum(noticias.NEWS_DECAY ** (i - 1) for i in range(1, h + 1))


def fng_at(by_day, d):
    """Índice publicado al cierre del día d (el del día siguiente a las 00:00 UTC)."""
    v = by_day.get(d + 1, by_day.get(d))
    prev = [by_day.get(d + 1 - k, by_day.get(d - k)) for k in range(1, 8)]
    prev = [p for p in prev if p is not None]
    if v is None:
        return 0.0, 50.0
    return (v - sum(prev) / len(prev) if prev else 0.0), v


def hist_base(i, logs, days, scores, by_day):
    """Lo que se sabía al cierre del día i (no depende del horizonte)."""
    slope = noticias.trend_slope(logs[max(0, i - noticias.TREND_DAYS + 1): i + 1])
    lo = max(1, i - 89)
    sigma = noticias._stdev([logs[j] - logs[j - 1] for j in range(lo, i + 1)])
    delta, level = fng_at(by_day, days[i])
    return slope, delta, level, scores.get(days[i], 0), logs[i] - logs[i - 7], sigma


# ─────────────────────────── BASE DE DATOS ───────────────────────────

def init(store):
    with store.lock:
        store.db.execute("""CREATE TABLE IF NOT EXISTS ia_pred (coin TEXT, day INTEGER, h INTEGER,
            t_made INTEGER, p0 REAL, x TEXT, ai REAL, formula REAL, actual REAL,
            PRIMARY KEY (coin, day, h))""")
        store.db.commit()


def load(store, coin):
    m = store.get(f"ia:{coin}")
    if not m or m.get("v") != VERSION:
        m = {"v": VERSION, "h": {str(h): new_model() for h in range(1, H_MAX + 1)}}
    return m


def save(store, coin, m):
    store.put(f"ia:{coin}", m)


def live_records(store, coin, day_from):
    with store.lock:
        rows = store.db.execute("SELECT day, h, x, formula, actual FROM ia_pred WHERE coin=? AND day>=?",
                                (coin, day_from)).fetchall()
    return {(d, h): (json.loads(x), f, a) for d, h, x, f, a in rows}


# ─────────────────────────── APRENDER ───────────────────────────

def learn(store, coin, closes, scores, fng):
    """Aprende de todos los días cuyo resultado ya se conoce y aún no ha visto.
    closes: [(t, cierre)] cerradas; scores: [(t, puntuación)]; fng: [(t, valor)] o None."""
    if len(closes) < 120:
        return None
    with _lock:
        m = load(store, coin)
        days = [t // DAY_MS for t, _ in closes]
        logs = [math.log(c) for _, c in closes]
        sc = {t // DAY_MS: s for t, s in scores}
        by_day = {t // DAY_MS: v for t, v in (fng or [])}
        start_i = max(100, len(closes) - BACKFILL_DAYS)
        live = live_records(store, coin, days[start_i])
        resolved, base_cache = [], {}
        for hs, mh in m["h"].items():
            h = int(hs)
            first = start_i if mh["last_d"] is None else None
            for i in range(start_i, len(closes) - h):
                d = days[i]
                if first is None and d <= mh["last_d"]:
                    continue
                y = logs[i + h] - logs[i]
                rec = live.get((d, h))
                if rec:                      # una predicción propia: con noticias
                    x, f_pred, _ = rec
                    mh["n_live"] += 1
                    resolved.append((d, h, y))
                else:                        # un día del historial
                    if i not in base_cache:
                        base_cache[i] = hist_base(i, logs, days, sc, by_day)
                    slope, delta, level, score, ret7, sigma = base_cache[i]
                    x = make_x(h, slope, 0.0, delta, level, score, ret7, sigma)
                    f_pred = slope * noticias.damp_sum(h)
                p = rls_predict(mh, x)
                if mh["n"] >= 30:            # evaluación honesta: antes de ver el resultado
                    mh["e_ai"] = ema(mh["e_ai"], (p - y) ** 2)
                    mh["e_f"] = ema(mh["e_f"], (f_pred - y) ** 2)
                    mh["e_0"] = ema(mh["e_0"], y ** 2)
                    if abs(y) > 1e-9 and abs(p) > 1e-9:
                        mh["hit_n"] += 1
                        mh["hit"] += (p > 0) == (y > 0)
                rls_update(mh, x, max(-0.4, min(0.4, y)))
                mh["n"] += 1
                for j in range(K):           # escala de cada característica (para "qué pesa")
                    mh["fm"][j] = (1 - ALPHA) * mh["fm"][j] + ALPHA * x[j]
                    mh["fv"][j] = (1 - ALPHA) * mh["fv"][j] + ALPHA * (x[j] - mh["fm"][j]) ** 2
                mh["last_d"] = d
        if resolved:
            with store.lock:
                store.db.executemany("UPDATE ia_pred SET actual=? WHERE coin=? AND day=? AND h=?",
                                     [(y, coin, d, h) for d, h, y in resolved])
                store.db.commit()
        save(store, coin, m)
        return m


# ─────────────────────────── PREDECIR ───────────────────────────

def blend_weight(mh):
    """Peso de la IA en la predicción final, según su error frente al de la fórmula."""
    if mh["e_ai"] is None or mh["e_f"] is None or mh["n"] < 60:
        return 0.3
    return max(0.1, min(0.9, mh["e_f"] / (mh["e_f"] + mh["e_ai"])))


def predict(store, coin, r, res):
    """Añade a res["forecast"] la predicción de la IA y la final (IA + fórmula), guarda la
    predicción para evaluarla cuando llegue el precio real y añade res["ia"] con su estado."""
    closes = r["closes"]
    fc = res["forecast"]
    fng = None
    try:
        fng = noticias.fear_greed()
    except Exception:
        pass
    m = learn(store, coin, closes, r.get("scores", []), fng)
    if m is None:
        return
    days = [t // DAY_MS for t, _ in closes]
    logs = [math.log(c) for _, c in closes]
    i = len(closes) - 1
    d_last = days[i]
    by_day = {t // DAY_MS: v for t, v in (fng or [])}
    delta, level = fng_at(by_day, d_last)
    lo = max(1, i - 89)
    sigma = noticias._stdev([logs[j] - logs[j - 1] for j in range(lo, i + 1)])
    slope = fc["slope"]
    move_today = math.log(r["price"]) - logs[i]       # lo que lleva hoy (vela sin cerrar)

    rows, out = [], []
    for k in range(1, H_MAX + 1):
        x = make_x(k, slope, news_term(res["signal"], res["news_weight"], sigma, k), delta, level,
                   r.get("score", 0), logs[i] - logs[i - 7], sigma)
        ai = rls_predict(m["h"][str(k)], x)
        cap = 3 * sigma * math.sqrt(k)
        ai = max(-cap, min(cap, ai))
        # la fórmula, medida igual que la IA: desde el último cierre
        f = move_today + (math.log(1 + fc["days"][k - 2]["pct"]) if k >= 2 else 0.0)
        rows.append((coin, d_last, k, res["time"], closes[i][1], json.dumps(x), ai, f))
        out.append((ai, f))
    with store.lock:  # la primera predicción de cada día es la que se evalúa
        store.db.executemany("INSERT OR IGNORE INTO ia_pred (coin, day, h, t_made, p0, x, ai, formula) "
                             "VALUES (?,?,?,?,?,?,?,?)", rows)
        store.db.commit()

    # día h del panel (≈ ahora + h días) = cierre del día d_last + h + 1
    p_now = r["price"]
    for h, dd in enumerate(fc["days"], start=1):
        ai_k, _ = out[h]                               # horizonte k = h + 1
        mh = m["h"][str(h + 1)]
        w = blend_weight(mh)
        ai_from_now = ai_k - move_today
        f_from_now = math.log(dd["pred"] / p_now)
        fin = w * ai_from_now + (1 - w) * f_from_now
        band = math.log(dd["hi"] / dd["pred"])
        dd.update({"ai": p_now * math.exp(ai_from_now), "ai_pct": math.exp(ai_from_now) - 1,
                   "formula": dd["pred"], "formula_pct": dd["pct"], "w_ai": w,
                   "pred": p_now * math.exp(fin), "pct": math.exp(fin) - 1,
                   "lo": p_now * math.exp(fin - band), "hi": p_now * math.exp(fin + band)})
    res["ia"] = status(store, coin, m)


def status(store, coin, m):
    mh = m["h"]["3"] if "3" in m["h"] else next(iter(m["h"].values()))

    def rmse(v):
        return math.sqrt(v) if v is not None else None
    imp = []
    for j in range(1, K):
        imp.append((abs(mh["w"][j]) * math.sqrt(max(mh["fv"][j], 0)), FEATURES[j], mh["w"][j]))
    imp.sort(reverse=True)
    tot = sum(v for v, _, _ in imp) or 1
    with store.lock:
        last = store.db.execute(
            "SELECT day, h, ai, formula, actual FROM ia_pred WHERE coin=? AND h=3 AND actual IS NOT NULL "
            "ORDER BY day DESC LIMIT 6", (coin,)).fetchall()
        pending = store.db.execute("SELECT COUNT(*) FROM ia_pred WHERE coin=? AND actual IS NULL",
                                   (coin,)).fetchone()[0]
        live_tot = store.db.execute("SELECT COUNT(*) FROM ia_pred WHERE coin=? AND actual IS NOT NULL",
                                    (coin,)).fetchone()[0]
    return {
        "n": sum(x["n"] for x in m["h"].values()), "n_live": live_tot, "pending": pending,
        "rmse_ai": rmse(mh["e_ai"]), "rmse_f": rmse(mh["e_f"]), "rmse_0": rmse(mh["e_0"]),
        "hit": round(100 * mh["hit"] / mh["hit_n"]) if mh["hit_n"] else None, "hit_n": mh["hit_n"],
        "w_ai": blend_weight(mh), "news_factor": mh["w"][2] / noticias.NEWS_K,
        "news_samples": mh["n_live"],
        "importance": [(name, v / tot, w) for v, name, w in imp[:3]],
        "last": [{"day": d * DAY_MS, "ai": a, "formula": f, "actual": y} for d, _, a, f, y in last],
    }
