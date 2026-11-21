"""
Manual de Cripto Señales para Android (se ve con el botón «i» de la app).
Autor: Luis Tranche Casado

Formato sencillo: "# " título de sección, "- " viñeta, "1. " paso, **negrita**.
"""

MANUAL = """
# Cripto Señales para Android
**Autor: Luis Tranche Casado**

Cripto Señales dice, para cada criptomoneda que elijas, si los indicadores apuntan a comprar, vender o esperar, y qué se espera para los próximos 5 días. Hace los mismos cálculos que el programa de escritorio.

No necesita cuenta, clave ni pago: los datos salen de fuentes públicas y gratuitas. No compra ni vende nada por ti.

**Importante:** son indicadores técnicos y estimaciones estadísticas. No garantizan resultados y no son asesoramiento financiero.

# Primer uso
1. Abre la app con conexión a internet.
2. Descarga unos 1.500 días de precios de cada moneda y la IA estudia unos 2 años de historial. Tarda un poco la primera vez.
3. Después busca las noticias de cada moneda. Mientras tanto el semáforo pone «calculando...». Completar todas puede tardar uno o dos minutos.

Las siguientes veces es mucho más rápido. Los precios se actualizan cada 15 minutos y las noticias cada 20 mientras la app está abierta.

# Pantalla principal
Una tarjeta por moneda con:
- **Moneda y precio** actual en dólares (USDT).
- **Señal técnica:** COMPRAR (verde), VENDER (rojo) o ESPERAR (gris), con su puntuación de -100 a +100.
- **Semáforo:** COMPRA, PRECAUCIÓN o VENDE (ver más abajo).
- **Desde:** día en que empezó la señal y cuánto ha variado el precio desde entonces.
- **Compra prob. / Venta prob.:** fechas probables de la próxima señal, según lo que han durado los ciclos pasados de esa moneda.
- Si indicaste tu compra, lo que ganas o pierdes.

Botones de arriba: **i** abre este manual, **Monedas** cambia la lista (separadas por comas, deben existir frente a USDT en Binance) y **Actualizar** descarga los precios al momento.

Toca una tarjeta para ver su detalle. El botón atrás del móvil vuelve a la lista.

# Detalle de una moneda
- **Semáforo** y el motivo.
- **Gráfico:** línea blanca, el precio de los últimos 45 días; punteada gris, la tendencia sola; morada, la predicción de la IA; verde o roja, la predicción final. La zona sombreada es el rango probable (unos 2 de cada 3 casos).
- **Predicción día a día** con su rango y el desglose IA / fórmula.
- **Tu compra** (ver más abajo).
- **Qué ha aprendido la IA.**
- **Noticias recientes** y **noticias que movieron el precio**. Toca un titular para abrir la noticia.

El botón **Noticias** de arriba las vuelve a buscar al momento.

# Señal técnica
La puntuación suma seis indicadores sobre las velas diarias cerradas: media de 200 días, cruce de medias 50/200, MACD, RSI, bandas de Bollinger y volumen (OBV). Cambia como mucho una vez al día, a las 00:00 UTC.

Para no cambiar de opinión cada día:
- Pasa a **COMPRAR** con +40 o más y vuelve a ESPERAR cuando baja de +10.
- Pasa a **VENDER** con -40 o menos y vuelve a ESPERAR cuando sube de -10.

**Acierto 30 d:** porcentaje de señales pasadas de esa moneda que acertaron la dirección 30 días después.

# Tu compra
En el detalle de una moneda, escribe la fecha en que compraste (14/03/25, 14/03/2025 o 2025-03-14) y, si quieres, el precio en dólares (62.000 o 0,4512; los decimales van con coma). Pulsa **Guardar**. Si dejas el precio vacío se usa el cierre de ese día. Para quitarla, borra la fecha y guarda.

Con tu compra, «Venta prob.» te dice si vender te deja al menos un 3 % de beneficio (lo que cubre comisiones):
- **AHORA +x%** en verde: la señal dice VENDER y ganas.
- **AHORA -x% (!)** en naranja: la señal dice VENDER pero perderías.
- **ya pasó ...** en naranja: desde tu compra ya hubo una señal de venta con beneficio.
- Una fecha y **>= precio**: aún no toca vender y vas perdiendo; es el precio que necesitas.

# Semáforo
Resume la predicción final a 5 días, la que mezcla la IA con la fórmula de noticias:
- **Verde, COMPRA:** se espera una subida clara.
- **Naranja, PRECAUCIÓN:** el movimiento previsto es pequeño, o la IA y la fórmula apuntan en sentidos contrarios.
- **Rojo, VENDE:** se espera una bajada clara.

«Clara» es más de un cuarto de lo que esa moneda suele moverse en 5 días (en BTC, en torno a 1,5-2 %). El semáforo y la señal técnica miden cosas distintas: la señal es la tendencia de fondo (semanas); el semáforo, los próximos 5 días.

# Noticias y predicción
Fuentes: Google Noticias (en inglés y español), CoinDesk, Cointelegraph, Decrypt y el índice de miedo y codicia del mercado cripto.

Cada titular recibe un tono de -1 (muy bajista) a +1 (muy alcista) con un diccionario de palabras. Es orientativo: puede equivocarse con titulares irónicos o ambiguos.

La predicción por fórmula suma tres partes: la tendencia de los últimos 20 días prolongada y perdiendo fuerza, la corrección por el tono de las noticias (con más peso cuanto más hayan acertado con esa moneda) y la corrección por el índice de miedo y codicia.

# Módulo de IA
La IA aprende sola: al principio estudia unos 2 años de historial de cada moneda; después aprende de cada día que cierra y de sus propias predicciones, que guarda y comprueba cuando llega el precio real. Así aprende también cuánto pesan de verdad las noticias.

Lleva la cuenta de su error, del de la fórmula y del de suponer que «no cambia nada». La predicción final da más peso a la que se está equivocando menos.

La IA del móvil aprende por su cuenta, separada de la del ordenador. Cuanto más uses la app, más aprende. Si acierta la dirección cerca del 50 %, el mercado no está siguiendo patrones claros: es la medida honesta de cuánto fiarse.

# Datos
Todo se guarda dentro de la app (precios, noticias pasadas, lo aprendido por la IA, tus monedas y compras). Si borras los datos de la app desde los ajustes de Android, empieza de cero.

La app solo trabaja mientras está abierta: al volver a abrirla descarga lo que falte.

# Problemas frecuentes
- **«historial insuficiente o par inexistente»:** la moneda no existe frente a USDT en Binance o es muy nueva.
- **El semáforo se queda en «calculando...»:** espera uno o dos minutos; si sigue, abre la moneda y pulsa Noticias.
- **«Fuentes que no han respondido»:** alguna fuente no está disponible; la app sigue con las demás.
- **No se actualiza nada:** comprueba la conexión a internet y pulsa Actualizar.

# Aviso legal y créditos
**Autor: Luis Tranche Casado.**

Cripto Señales ofrece indicadores técnicos, análisis del tono de noticias y estimaciones estadísticas sobre datos pasados. No garantiza resultados futuros ni es asesoramiento financiero. Cada decisión es responsabilidad de quien la toma. Invierte solo lo que puedas permitirte perder.

Datos: precios de Binance; noticias de Google Noticias, CoinDesk, Cointelegraph y Decrypt; índice de miedo y codicia de alternative.me. Hecho con Python y Kivy.
"""
