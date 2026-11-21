"""
Cripto Señales para Android (Kivy)
Autor: Luis Tranche Casado

Pantallas:
  lista    una tarjeta por moneda: precio, señal técnica, semáforo, fechas probables
  detalle  semáforo, gráfico, predicción, tu compra, lo que ha aprendido la IA, noticias
  manual   el manual (botón «i»)
Todo el cálculo está en nucleo.py, noticias.py y aprendizaje.py (los mismos del escritorio).
"""

import math
import os
import re
import time
import webbrowser
from datetime import datetime

# certificados para las conexiones seguras (https) en Android
try:
    import certifi
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
except Exception:
    pass

from kivy.app import App
from kivy.clock import Clock
from kivy.core.text import Label as CoreLabel
from kivy.core.window import Window
from kivy.graphics import Color, Ellipse, Line, Mesh, Rectangle, RoundedRectangle
from kivy.metrics import dp, sp
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import Screen, ScreenManager, SlideTransition
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget
from kivy.utils import escape_markup, get_color_from_hex as hexc

import manual_android
import nucleo as N

BG, CARD, LINE = "#0e1217", "#141a22", "#2a3544"
TEXT, MUTED, DIM, BLUE, PURPLE = "#d5dde8", "#8fa0b5", "#6d7b8c", "#4aa8ff", "#b48cff"
CALC = ("calculando...", MUTED, "#1a2330")
WEEKDAYS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]


def open_url(url):
    """Abre un enlace en el navegador del móvil (Android) o del ordenador (pruebas)."""
    try:
        from jnius import autoclass
        Intent = autoclass("android.content.Intent")
        Uri = autoclass("android.net.Uri")
        activity = autoclass("org.kivy.android.PythonActivity").mActivity
        activity.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
    except Exception:
        webbrowser.open(url)


def c(hex_):
    return hex_.lstrip("#")


def esc(s):
    return escape_markup(N.plain(str(s)))


def col(text, hex_):
    return f"[color={c(hex_)}]{text}[/color]"


# ─────────────────────────── PIEZAS ───────────────────────────

class Txt(Label):
    """Texto que ocupa el ancho disponible y crece hacia abajo (con marcas [b], [color]...)."""

    def __init__(self, text="", size=14, **kw):
        kw.setdefault("color", hexc(TEXT))
        super().__init__(text=text, markup=True, font_size=sp(size), halign="left", valign="top",
                         size_hint_y=None, **kw)
        self.bind(width=lambda *a: setattr(self, "text_size", (self.width, None)),
                  texture_size=lambda *a: setattr(self, "height", self.texture_size[1]))


class Cell(Label):
    """Texto de una sola línea, alineado y recortado si no cabe."""

    def __init__(self, text="", size=14, halign="left", **kw):
        kw.setdefault("color", hexc(TEXT))
        super().__init__(text=text, markup=True, font_size=sp(size), halign=halign, valign="middle",
                         shorten=True, shorten_from="right", **kw)
        self.bind(size=lambda *a: setattr(self, "text_size", self.size))


class Pill(Label):
    """El semáforo: letras y borde del color del estado sobre fondo del mismo tono."""

    def __init__(self, **kw):
        super().__init__(bold=True, font_size=sp(13), **kw)
        with self.canvas.before:
            self._bgc = Color(*hexc(CALC[2]))
            self._bg = RoundedRectangle(radius=[dp(8)])
            self._lc = Color(*hexc(CALC[1]))
            self._ln = Line(width=dp(1))
        self.bind(pos=self._upd, size=self._upd)
        self.set(None)

    def set(self, kind):
        label, fg, bg = N.LIGHTS[kind] if kind in N.LIGHTS else CALC
        self.text = label
        self.color = hexc(fg)
        self._bgc.rgba = hexc(bg)
        self._lc.rgba = hexc(fg if kind else LINE)

    def _upd(self, *a):
        self._bg.pos, self._bg.size = self.pos, self.size
        self._ln.rounded_rectangle = (self.x, self.y, self.width, self.height, dp(8))


class Panel(BoxLayout):
    """Caja con fondo de tarjeta."""

    def __init__(self, **kw):
        kw.setdefault("orientation", "vertical")
        kw.setdefault("padding", dp(10))
        kw.setdefault("spacing", dp(4))
        kw.setdefault("size_hint_y", None)
        super().__init__(**kw)
        self.bind(minimum_height=self.setter("height"))
        with self.canvas.before:
            Color(*hexc(CARD))
            self._bg = RoundedRectangle(radius=[dp(10)])
        self.bind(pos=lambda *a: setattr(self._bg, "pos", self.pos),
                  size=lambda *a: setattr(self._bg, "size", self.size))


def top_bar(title, buttons):
    bar = BoxLayout(size_hint_y=None, height=dp(52), padding=(dp(10), dp(6)), spacing=dp(6))
    with bar.canvas.before:
        Color(*hexc("#101721"))
        r = Rectangle()
    bar.bind(pos=lambda *a: setattr(r, "pos", bar.pos), size=lambda *a: setattr(r, "size", bar.size))
    bar.title = Cell(f"[b]{title}[/b]", size=18, color=hexc(BLUE))
    bar.add_widget(bar.title)
    for text, cb, w in buttons:
        b = Button(text=text, size_hint_x=None, width=dp(w), font_size=sp(14),
                   background_normal="", background_color=hexc("#1a2330"), color=hexc(TEXT))
        b.bind(on_release=lambda *_a, f=cb: f())
        bar.add_widget(b)
    return bar


def scroller():
    sv = ScrollView(do_scroll_x=False, bar_width=dp(4))
    box = BoxLayout(orientation="vertical", size_hint_y=None, padding=dp(10), spacing=dp(8))
    box.bind(minimum_height=box.setter("height"))
    sv.add_widget(box)
    return sv, box


# ─────────────────────────── LISTA DE MONEDAS ───────────────────────────

class CoinCard(ButtonBehavior, Panel):
    def __init__(self, coin, **kw):
        super().__init__(**kw)
        self.coin = coin
        top = BoxLayout(size_hint_y=None, height=dp(34), spacing=dp(6))
        self.name = Cell(f"[b]{coin}[/b]", size=18, size_hint_x=0.22)
        self.price = Cell("", size=16, size_hint_x=0.3)
        self.signal = Cell("", size=13, size_hint_x=0.48, halign="right")
        top.add_widget(self.name)
        top.add_widget(self.price)
        top.add_widget(self.signal)
        mid = BoxLayout(size_hint_y=None, height=dp(30), spacing=dp(8))
        self.since = Cell("", size=12, color=hexc(MUTED))
        self.pill = Pill(size_hint_x=None, width=dp(130))
        mid.add_widget(self.since)
        mid.add_widget(self.pill)
        self.dates = Txt("", size=12, color=hexc(MUTED))
        self.add_widget(top)
        self.add_widget(mid)
        self.add_widget(self.dates)

    def show(self, row):
        if not row:
            self.price.text = col("sin datos", DIM)
            return
        st = row["state"]
        sc = N.COLORS.get(st, MUTED)
        self.price.text = f"{row['price']} $"
        score = "%+d" % row["score"]
        self.signal.text = "[b]" + col(st, sc) + "[/b] " + col(score, sc)
        self.since.text = f"desde {row['since']} ({row['delta']})"
        self.pill.set(row.get("light"))
        sell_c = N.HOLD_COLORS.get(row["sell_kind"], N.SELL_DATE_COLOR) if row["sell_kind"] else N.SELL_DATE_COLOR
        txt = (f"Compra prob. {col(esc(row['buy']), N.BUY_DATE_COLOR)}   ·   "
               f"Venta prob. {col(esc(row['sell']), sell_c)}")
        if row["gain"] is not None:
            g = row["gain"]
            txt += f"\nTu compra {esc(row['bought'])}: {col(N.pct(g), N.GAIN_UP if g >= 0 else N.GAIN_DOWN)}"
        self.dates.text = txt


class ListScreen(Screen):
    def __init__(self, app, **kw):
        super().__init__(**kw)
        self.app = app
        root = BoxLayout(orientation="vertical")
        root.add_widget(top_bar("Cripto Señales", [("i", app.show_manual, 44),
                                                    ("Monedas", self.edit_coins, 92),
                                                    ("Actualizar", app.nu.refresh, 104)]))
        self.status = Cell("Descargando datos...", size=12, color=hexc(MUTED),
                           size_hint_y=None, height=dp(24), padding=(dp(12), 0))
        root.add_widget(self.status)
        sv, self.box = scroller()
        root.add_widget(sv)
        root.add_widget(Txt("Indicadores y estimaciones estadísticas: no son asesoramiento financiero.",
                            size=11, color=hexc(DIM), padding=(dp(12), dp(6))))
        self.add_widget(root)
        self.cards = {}

    def rebuild(self):
        self.box.clear_widgets()
        self.cards = {}
        for coin in self.app.nu.coins:
            card = CoinCard(coin)
            card.bind(on_release=lambda w: self.app.open_detail(w.coin))
            self.cards[coin] = card
            self.box.add_widget(card)
        self.refresh_cards()

    def refresh_cards(self, coin=None):
        for k, card in self.cards.items():
            if coin is None or k == coin:
                card.show(self.app.nu.row(k))

    def edit_coins(self):
        box = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(10))
        box.add_widget(Txt("Monedas separadas por comas (deben existir frente a USDT en Binance):",
                           size=13, color=hexc(MUTED)))
        ti = TextInput(text=", ".join(self.app.nu.coins), multiline=False, font_size=sp(16),
                       size_hint_y=None, height=dp(44))
        box.add_widget(ti)
        ok = Button(text="Guardar", size_hint_y=None, height=dp(44))
        box.add_widget(ok)
        pop = Popup(title="Monedas", content=box, size_hint=(0.92, None), height=dp(250))

        def save(*_a):
            if self.app.nu.set_coins(ti.text):
                self.rebuild()
            pop.dismiss()
        ok.bind(on_release=save)
        pop.open()


# ─────────────────────────── GRÁFICO ───────────────────────────

class Chart(Widget):
    def __init__(self, **kw):
        super().__init__(size_hint_y=None, height=dp(230), **kw)
        self.res = None
        self.bind(pos=lambda *a: self.redraw(), size=lambda *a: self.redraw())

    def set(self, res):
        self.res = res
        self.redraw()

    def _text(self, txt, x, y, hex_, anchor="left"):
        lb = CoreLabel(text=txt, font_size=sp(10))
        lb.refresh()
        tex = lb.texture
        dx = {"left": 0, "right": tex.width, "center": tex.width / 2}[anchor]
        Color(*hexc(hex_))
        Rectangle(texture=tex, size=tex.size, pos=(x - dx, y - tex.height / 2))

    def redraw(self):
        self.canvas.clear()
        res = self.res
        if not res or self.width < 10:
            return
        days = res["forecast"]["days"]
        hist = [(t + N.DAY_MS, v) for t, v in res["history"]]
        now_t, now_p = res["time"], res["price"]
        pts = hist + [(now_t, now_p)]
        ys = [v for _, v in pts] + [d["lo"] for d in days] + [d["hi"] for d in days]
        ys += [d["ai"] for d in days if "ai" in d]
        y0, y1 = min(ys), max(ys)
        pad = (y1 - y0) * 0.08 or y1 * 0.01
        y0, y1 = y0 - pad, y1 + pad
        t0, t1 = pts[0][0], days[-1]["t"]
        L, R, T, B = dp(4), dp(62), dp(8), dp(18)

        def X(t):
            return self.x + L + (t - t0) / (t1 - t0) * (self.width - L - R)

        def Y(v):
            return self.y + B + (v - y0) / (y1 - y0) * (self.height - T - B)

        with self.canvas:
            for k in range(4):   # rejilla y precios
                v = y0 + (y1 - y0) * k / 3
                Color(*hexc("#1b2430"))
                Line(points=[self.x + L, Y(v), self.right - R, Y(v)], width=1)
                self._text(N.fmt_price(v), self.right - R + dp(4), Y(v), DIM)
            Color(*hexc(LINE))
            Line(points=[X(now_t), self.y + B, X(now_t), self.top - T], width=1,
                 dash_length=dp(3), dash_offset=dp(3))
            # rango ±1σ
            v = [X(now_t), Y(now_p), 0, 0, X(now_t), Y(now_p), 0, 0]
            for d in days:
                v += [X(d["t"]), Y(d["hi"]), 0, 0, X(d["t"]), Y(d["lo"]), 0, 0]
            Color(74 / 255, 168 / 255, 1, 0.16)
            Mesh(vertices=v, indices=list(range(len(v) // 4)), mode="triangle_strip")

            def line(points, hex_, width=1.0, dashed=False):
                flat = [z for t, val in points for z in (X(t), Y(val))]
                Color(*hexc(hex_))
                if dashed:
                    Line(points=flat, width=1, dash_length=dp(2), dash_offset=dp(3))
                else:
                    Line(points=flat, width=width)

            line(pts, TEXT, dp(1.2))
            line([(now_t, now_p)] + [(d["t"], d["base"]) for d in days], MUTED, dashed=True)
            if "ai" in days[0]:
                line([(now_t, now_p)] + [(d["t"], d["ai"]) for d in days], PURPLE, dp(1.1))
            fin = N.GAIN_UP if days[-1]["pct"] >= 0 else N.GAIN_DOWN
            line([(now_t, now_p)] + [(d["t"], d["pred"]) for d in days], fin, dp(1.8))
            Color(*hexc(fin))
            for d in days:
                Ellipse(pos=(X(d["t"]) - dp(2.5), Y(d["pred"]) - dp(2.5)), size=(dp(5), dp(5)))
            self._text(N.fmt_date(pts[0][0] - N.DAY_MS), self.x + L, self.y + dp(8), DIM)
            self._text("hoy", X(now_t), self.y + dp(8), DIM, "center")
            self._text(datetime.fromtimestamp(days[-1]["t"] / 1000).strftime("%d/%m"),
                       self.right - R, self.y + dp(8), DIM, "right")


# ─────────────────────────── DETALLE ───────────────────────────

def news_line(x, links, date=True):
    """Un titular con su tono. El enlace se guarda en `links` y el texto lleva su número."""
    s = x["score"]
    tone = col(("%+.2f" % s).replace(".", ","), N.GAIN_UP if s >= 0.12 else N.GAIN_DOWN if s <= -0.12 else MUTED)
    when = datetime.fromtimestamp(x["t"] / 1000).strftime("%d/%m %H:%M") + "  " if date else ""
    title = esc(x["title"])
    link = x.get("link") or ""
    if link:
        links.append(link)
        title = f"[ref={len(links) - 1}][u]{title}[/u][/ref]"
    return f"{col(when, DIM)}[b]{tone}[/b]  {title} {col('· ' + esc(x['source']), DIM)}"


def ia_text(ia, coin):
    if not ia:
        return ""
    t = [f"Ha aprendido de [b]{ia['n']:,}[/b] casos · [b]{ia['n_live']}[/b] predicciones propias "
         f"evaluadas · {ia['pending']} esperando resultado.".replace(",", ".", 1)]
    if ia["rmse_ai"] is not None:
        better = ia["rmse_ai"] < ia["rmse_f"]
        ai_err = col("%.1f%%" % (100 * ia["rmse_ai"]), N.GAIN_UP if better else "#f0a030")
        t.append(("Error medio a 3 días: IA [b]" + ai_err + "[/b] · fórmula %.1f%% · «no cambia nada» %.1f%%"
                  % (100 * ia["rmse_f"], 100 * ia["rmse_0"])).replace(".", ","))
        if ia["hit"] is not None:
            t.append(f"Acierta la dirección el [b]{ia['hit']} %[/b] de {ia['hit_n']} veces.")
        t.append(f"A 3 días la IA pesa un [b]{ia['w_ai']:.0%}[/b] en la predicción final.")
    if ia["importance"]:
        parts = [f"{name} ({share:.0%}, {'sube' if w > 0 else 'baja'})" for name, share, w in ia["importance"]]
        t.append("Lo que más tiene en cuenta: " + ", ".join(parts) + ".")
    if ia["news_samples"] >= 20:
        t.append(f"Peso real de las noticias en {coin}: ×{ia['news_factor']:.1f} lo que suponía la fórmula."
                 .replace(".", ",", 1))
    else:
        t.append(col(f"Para medir cuánto pesan las noticias necesita unas 20 predicciones evaluadas "
                     f"(lleva {ia['news_samples']}).", DIM))
    for x in ia["last"][:4]:
        ok = (x["ai"] > 0) == (x["actual"] > 0)
        t.append(f"{col(N.fmt_date(x['day']), DIM)}  previsto [b]{N.pct(math.exp(x['ai']) - 1)}[/b] · "
                 f"real [b]{N.pct(math.exp(x['actual']) - 1)}[/b]  {'OK' if ok else '(!)'}")
    return "\n".join(t)


class DetailScreen(Screen):
    def __init__(self, app, **kw):
        super().__init__(**kw)
        self.app = app
        self.coin = None
        root = BoxLayout(orientation="vertical")
        self.bar = top_bar("", [("<", app.back, 44), ("Noticias", self.reload_news, 100)])
        self.bar.remove_widget(self.bar.title)
        self.bar.add_widget(self.bar.title, index=len(self.bar.children) - 1)
        root.add_widget(self.bar)
        sv, self.box = scroller()
        self.sv = sv
        root.add_widget(sv)
        self.add_widget(root)

    def open(self, coin):
        if coin != self.coin:
            self.sv.scroll_y = 1
        self.coin = coin
        self.bar.title.text = f"[b]{coin}[/b]"
        self.render()
        if not self.app.nu.is_fresh(coin):
            self.app.nu.refresh_news(coin)

    def reload_news(self):
        if self.coin:
            self.app.nu.refresh_news(self.coin, force=True)
            self.render()

    def section(self, title):
        return Txt(f"[b]{col(title, BLUE)}[/b]", size=15)

    def render(self):
        nu, coin = self.app.nu, self.coin
        self.box.clear_widgets()
        self.links = []
        row = nu.row(coin)
        res = nu.news.get(coin)
        if not row:
            self.box.add_widget(Txt(col("Aún no hay datos de esta moneda.", MUTED)))
            return

        # semáforo + señal
        p = Panel()
        head = BoxLayout(size_hint_y=None, height=dp(34), spacing=dp(8))
        pill = Pill(size_hint_x=None, width=dp(140))
        pill.set(row.get("light"))
        head.add_widget(pill)
        head.add_widget(Cell(f"[b]{row['price']} $[/b]", size=18, halign="right"))
        p.add_widget(head)
        if row.get("light"):
            p.add_widget(Txt(col(esc(row["light_why"]), MUTED), size=13))
        elif nu.working == coin:
            p.add_widget(Txt(col("Buscando noticias y calculando la predicción...", MUTED), size=13))
        else:
            p.add_widget(Txt(col("En cola: se calculará en unos momentos.", MUTED), size=13))
        sc = N.COLORS.get(row["state"], MUTED)
        p.add_widget(Txt(f"Señal técnica: [b]{col(row['state'], sc)}[/b] {row['score']:+d} desde {row['since']} "
                         f"({row['delta']}) · acierto 30 d {esc(row['hit'])}", size=13))
        p.add_widget(Txt(col("Motivos: " + esc(", ".join(row["reasons"])), DIM), size=12))
        self.box.add_widget(p)

        # gráfico y predicción
        if res:
            fc = res["forecast"]
            d = fc["days"]
            p = Panel()
            p.add_widget(self.section(f"Predicción a {len(d)} días"))
            ch = Chart()
            ch.set(res)
            p.add_widget(ch)
            p.add_widget(Txt(col("blanca: precio · gris punteada: tendencia · morada: IA · "
                                 "verde/roja: predicción final · sombreado: rango probable", DIM), size=11))
            last = d[-1]
            cc = N.GAIN_UP if last["pct"] >= 0 else N.GAIN_DOWN
            parts = (f"fórmula {N.pct(last.get('formula_pct', last['pct']))} (tendencia {N.pct(last['base_pct'])}, "
                     f"noticias {N.pct(last['news_pct'])}, miedo/codicia {N.pct(last['mood_pct'])})")
            if "ai_pct" in last:
                parts = f"IA {col(N.pct(last['ai_pct']), PURPLE)} × {last['w_ai']:.0%} + " + parts
            p.add_widget(Txt(f"[b]{col(N.fmt_price(last['pred']) + ' $ (' + N.pct(last['pct']) + ')', cc)}[/b]\n"
                             f"{col('= ' + parts, MUTED)}", size=13))
            rows = []
            for x in d:
                dt = datetime.fromtimestamp(x["t"] / 1000)
                xc = N.GAIN_UP if x["pct"] >= 0 else N.GAIN_DOWN
                rows.append(f"{col(f'{WEEKDAYS[dt.weekday()]} {dt:%d/%m}', MUTED)}   [b]{N.fmt_price(x['pred'])}[/b]"
                            f"  {col(N.pct(x['pct']), xc)}   {col(N.fmt_price(x['lo']) + ' - ' + N.fmt_price(x['hi']), DIM)}")
            p.add_widget(Txt("\n".join(rows), size=13))
            extra = []
            if fc["trend_hit"] is not None:
                extra.append(f"La tendencia sola acertó la dirección a 3 días el {fc['trend_hit']} % "
                             f"de {fc['trend_n']} días del último año.")
            f = fc["fng"]
            if f:
                extra.append(f"Miedo y codicia: {f['value']:.0f}/100, {f['delta']:+.0f} frente a la semana anterior.")
            if extra:
                p.add_widget(Txt(col(" ".join(extra), DIM), size=11))
            self.box.add_widget(p)

        # tu compra
        p = Panel()
        p.add_widget(self.section("Tu compra"))
        fields = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))
        bt = nu.bought.get(coin)
        d_txt = datetime.strptime(bt, "%Y-%m-%d").strftime("%d/%m/%y") if bt else ""
        p_txt = N.fmt_price(nu.bought_price[coin]) if coin in nu.bought_price else ""
        self.ti_date = TextInput(text=d_txt, hint_text="fecha dd/mm/aa", multiline=False, font_size=sp(15))
        self.ti_price = TextInput(text=p_txt, hint_text="precio $ (opcional)", multiline=False, font_size=sp(15))
        save = Button(text="Guardar", size_hint_x=None, width=dp(90))
        save.bind(on_release=lambda *_a: self.save_purchase())
        fields.add_widget(self.ti_date)
        fields.add_widget(self.ti_price)
        fields.add_widget(save)
        p.add_widget(fields)
        self.msg = Txt("", size=12, color=hexc(MUTED))
        p.add_widget(self.msg)
        if row["position"]:
            g = row["gain"]
            kind_c = N.HOLD_COLORS.get(row["sell_kind"], TEXT)
            p.add_widget(Txt(f"Venta: [b]{col(esc(row['sell']), kind_c)}[/b] · ahora "
                             f"{col(N.pct(g), N.GAIN_UP if g >= 0 else N.GAIN_DOWN)}", size=13))
            p.add_widget(Txt("\n".join("· " + esc(x) for x in row["position"]), size=12, color=hexc(MUTED)))
        else:
            p.add_widget(Txt(col("Si la tienes, escribe cuándo (y a cuánto) la compraste: la venta tendrá en "
                                 "cuenta si te deja beneficio.", DIM), size=12))
        self.box.add_widget(p)

        if not res:
            return
        # IA
        if res.get("ia"):
            p = Panel()
            p.add_widget(self.section("Qué ha aprendido la IA"))
            p.add_widget(Txt(ia_text(res["ia"], coin), size=12))
            self.box.add_widget(p)

        # noticias
        p = Panel()
        p.add_widget(self.section("Noticias recientes"))
        tr = res["tone48"] - res["tone7"]
        evo = "mejora" if tr > 0.1 else "empeora" if tr < -0.1 else "estable"
        p.add_widget(Txt(col(f"Tono 48 h {res['tone48']:+.2f} · semana {res['tone7']:+.2f} · {evo} · "
                             f"{res['n_recent']} noticias".replace(".", ","), MUTED), size=12))
        for x in res["recent"][:12]:
            t = Txt(news_line(x, self.links), size=13)
            t.bind(on_ref_press=self.open_link)
            p.add_widget(t)
        if not res["recent"]:
            p.add_widget(Txt(col("No se han encontrado noticias recientes.", DIM), size=12))
        self.box.add_widget(p)

        p = Panel()
        p.add_widget(self.section("Noticias que movieron el precio"))
        if res["judged"]:
            p.add_widget(Txt(col(f"El tono coincidió con el precio en {res['coherent']} de {res['judged']} "
                                 f"movimientos fuertes: la corrección por noticias cuenta al "
                                 f"{res['news_weight']:.0%}.", MUTED), size=12))
        if not res["events"]:
            p.add_widget(Txt(col("No ha habido movimientos fuertes en los últimos 120 días.", DIM), size=12))
        for e in res["events"]:
            v = {True: col("las noticias lo anticipaban", N.GAIN_UP), False: col("las noticias iban en contra", "#f0a030"),
                 None: col("tono poco claro", DIM)}[e["agree"]]
            ec = N.GAIN_UP if e["ret"] > 0 else N.GAIN_DOWN
            p.add_widget(Txt(f"[b]{N.fmt_date(e['t'])}  {col(N.pct(e['ret']), ec)}[/b]  {v}", size=13))
            for x in e["items"]:
                t = Txt(news_line(x, self.links, date=False), size=12)
                t.bind(on_ref_press=self.open_link)
                p.add_widget(t)
        if res["errors"]:
            p.add_widget(Txt(col("Fuentes que no han respondido: " + esc(" · ".join(res["errors"][:3])), DIM), size=11))
        self.box.add_widget(p)

    def open_link(self, _w, ref):
        try:
            open_url(self.links[int(ref)])
        except (ValueError, IndexError):
            pass

    def save_purchase(self):
        msg = self.app.nu.set_bought(self.coin, self.ti_date.text, self.ti_price.text)
        self.app.lista.refresh_cards(self.coin)
        self.render()
        self.msg.text = esc(msg)


# ─────────────────────────── MANUAL ───────────────────────────

def manual_markup(src):
    out = []
    for line in src.strip().split("\n"):
        line = line.rstrip()
        if not line:
            out.append("")
            continue
        body = escape_markup(N.plain(line))
        body = re.sub(r"\*\*(.+?)\*\*", r"[b]\1[/b]", body)
        if line.startswith("# "):
            out.append(f"\n[size={int(sp(18))}][b]{col(body[2:], BLUE)}[/b][/size]")
        elif line.startswith("- "):
            out.append("  •  " + body[2:])
        else:
            out.append(body)
    return "\n".join(out)


class ManualScreen(Screen):
    def __init__(self, app, **kw):
        super().__init__(**kw)
        root = BoxLayout(orientation="vertical")
        root.add_widget(top_bar("Manual", [("<", app.back, 44)]))
        sv, box = scroller()
        box.add_widget(Txt(manual_markup(manual_android.MANUAL), size=14))
        root.add_widget(sv)
        self.add_widget(root)


# ─────────────────────────── APLICACIÓN ───────────────────────────

class CriptoApp(App):
    title = "Cripto Señales"

    def build(self):
        Window.clearcolor = hexc(BG)
        self.nu = N.Nucleo(self.user_data_dir, self._from_worker)
        self.sm = ScreenManager(transition=SlideTransition(duration=0.18))
        self.lista = ListScreen(self, name="lista")
        self.detalle = DetailScreen(self, name="detalle")
        self.manual = None
        self.sm.add_widget(self.lista)
        self.sm.add_widget(self.detalle)
        self.lista.rebuild()
        Window.bind(on_keyboard=self._key)
        Clock.schedule_once(lambda dt: self.nu.refresh(), 0.5)
        Clock.schedule_interval(lambda dt: self.nu.refresh(), N.REFRESH_MIN * 60)
        Clock.schedule_interval(self._news_tick, N.NEWS_CACHE_MIN * 60)
        return self.sm

    # el núcleo avisa desde su hilo: se pasa al hilo de la interfaz
    def _from_worker(self, ev, coin):
        Clock.schedule_once(lambda dt: self._on_change(ev, coin))

    def _on_change(self, ev, coin):
        self.lista.status.text = esc(self.nu.status) + (f"  ·  buscando noticias de {coin}..."
                                                         if ev == "status" and coin else "")
        if ev == "prices":
            if set(self.lista.cards) != set(self.nu.coins):
                self.lista.rebuild()
            else:
                self.lista.refresh_cards()
        elif ev == "news":
            self.lista.refresh_cards(coin)
        if self.sm.current == "detalle" and (coin is None or coin == self.detalle.coin) and ev != "status":
            self.detalle.render()

    def _news_tick(self, dt):
        for c_ in self.nu.coins:
            if not self.nu.is_fresh(c_):
                self.nu.refresh_news(c_, front=False)

    def open_detail(self, coin):
        self.sm.transition.direction = "left"
        self.detalle.open(coin)
        self.sm.current = "detalle"

    def show_manual(self):
        if self.manual is None:
            self.manual = ManualScreen(self, name="manual")
            self.sm.add_widget(self.manual)
        self.sm.transition.direction = "left"
        self.sm.current = "manual"

    def back(self):
        self.sm.transition.direction = "right"
        self.sm.current = "lista"

    def _key(self, _win, key, *_a):
        if key == 27 and self.sm.current != "lista":   # botón «atrás» de Android
            self.back()
            return True
        return False

    def on_pause(self):
        return True

    def on_resume(self):
        self.nu.refresh()


if __name__ == "__main__":
    CriptoApp().run()
