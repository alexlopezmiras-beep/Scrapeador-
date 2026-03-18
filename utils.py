“””
utils.py — Utilidades generales: HTTP, parseo, logging, persistencia, notificaciones.
“””

import json
import logging
import os
import random
import re
import smtplib
import time
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

import requests

import config

# ─────────────────────────────────────────────

# LOGGING

# ─────────────────────────────────────────────

def setup_logging(log_file: str = “scraper.log”) -> logging.Logger:
“”“Configura logger con salida a consola y archivo.”””
logger = logging.getLogger(“idealista_scraper”)
logger.setLevel(logging.DEBUG)

```
fmt = logging.Formatter(
    "[%(asctime)s] %(levelname)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# Consola
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
ch.setFormatter(fmt)

# Archivo
fh = logging.FileHandler(log_file, encoding="utf-8")
fh.setLevel(logging.DEBUG)
fh.setFormatter(fmt)

if not logger.handlers:
    logger.addHandler(ch)
    logger.addHandler(fh)

return logger
```

logger = setup_logging()

# ─────────────────────────────────────────────

# DIRECTORIO DE SALIDA

# ─────────────────────────────────────────────

def ensure_output_dir():
“”“Crea el directorio de salida si no existe.”””
Path(config.OUTPUT_DIR).mkdir(parents=True, exist_ok=True)

# ─────────────────────────────────────────────

# HTTP CON ANTI-BLOQUEO

# ─────────────────────────────────────────────

def get_random_headers() -> dict:
“”“Devuelve headers HTTP con User-Agent aleatorio.”””
ua = random.choice(config.USER_AGENTS)
return {
“User-Agent”: ua,
“Accept”: “text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8”,
“Accept-Language”: “es-ES,es;q=0.9,en;q=0.8”,
“Accept-Encoding”: “gzip, deflate, br”,
“Connection”: “keep-alive”,
“Upgrade-Insecure-Requests”: “1”,
“Sec-Fetch-Dest”: “document”,
“Sec-Fetch-Mode”: “navigate”,
“Sec-Fetch-Site”: “none”,
“Cache-Control”: “max-age=0”,
“DNT”: “1”,
}

def random_delay():
“”“Pausa aleatoria entre peticiones (anti-bloqueo).”””
delay = random.uniform(config.DELAY_MIN, config.DELAY_MAX)
logger.debug(f”Esperando {delay:.1f}s antes de la siguiente petición…”)
time.sleep(delay)

def fetch_url(url: str, session: Optional[requests.Session] = None) -> Optional[str]:
“””
Descarga una URL con reintentos, delays y rotación de User-Agent.
Devuelve el HTML como string o None si falla.
“””
requester = session or requests

```
for attempt in range(1, config.MAX_RETRIES + 1):
    try:
        logger.info(f"[Intento {attempt}/{config.MAX_RETRIES}] GET {url[:80]}...")
        response = requester.get(
            url,
            headers=get_random_headers(),
            timeout=config.REQUEST_TIMEOUT,
            proxies=config.PROXIES,
            allow_redirects=True,
        )
        if response.status_code == 200:
            return response.text
        elif response.status_code == 403:
            logger.warning("HTTP 403 — Posible bloqueo. Esperando más tiempo...")
            time.sleep(config.RETRY_WAIT * 2)
        elif response.status_code == 429:
            logger.warning("HTTP 429 — Rate limit. Esperando...")
            time.sleep(config.RETRY_WAIT * 3)
        else:
            logger.warning(f"HTTP {response.status_code} para {url}")
            time.sleep(config.RETRY_WAIT)

    except requests.exceptions.Timeout:
        logger.error(f"Timeout en intento {attempt} para {url}")
        time.sleep(config.RETRY_WAIT)
    except requests.exceptions.ConnectionError as e:
        logger.error(f"Error de conexión en intento {attempt}: {e}")
        time.sleep(config.RETRY_WAIT)
    except Exception as e:
        logger.error(f"Error inesperado en intento {attempt}: {e}")
        time.sleep(config.RETRY_WAIT)

logger.error(f"Fallaron todos los intentos para: {url}")
return None
```

# ─────────────────────────────────────────────

# PARSEO DE TEXTO

# ─────────────────────────────────────────────

def parse_price(text: str) -> Optional[float]:
“”“Extrae precio numérico de un string como ‘185.000 €’.”””
if not text:
return None
cleaned = re.sub(r”[^\d.,]”, “”, text).replace(”.”, “”).replace(”,”, “.”)
try:
return float(cleaned)
except ValueError:
return None

def parse_m2(text: str) -> Optional[float]:
“”“Extrae metros cuadrados de un string como ‘85 m²’.”””
if not text:
return None
match = re.search(r”(\d+(?:[.,]\d+)?)\s*m”, text, re.IGNORECASE)
if match:
return float(match.group(1).replace(”,”, “.”))
return None

def parse_hours_since_publication(text: str) -> Optional[int]:
“””
Intenta convertir el texto de antigüedad del anuncio a horas.
Ejemplos: ‘hace 2 horas’, ‘hace 1 día’, ‘hace 3 días’, ‘nuevo’
“””
if not text:
return None
text_lower = text.lower().strip()
if any(k in text_lower for k in [“nuevo”, “new”, “hoy”, “today”, “recién”, “recien”]):
return 0
match_hours = re.search(r”(\d+)\s*hora”, text_lower)
if match_hours:
return int(match_hours.group(1))
match_days = re.search(r”(\d+)\s*d[íi]a”, text_lower)
if match_days:
return int(match_days.group(1)) * 24
match_weeks = re.search(r”(\d+)\s*semana”, text_lower)
if match_weeks:
return int(match_weeks.group(1)) * 24 * 7
return None

def extract_zone_from_url(url: str) -> str:
“”“Extrae zona aproximada de la URL de Idealista.”””
patterns = [
(r”elche.*altabix”, “elche altabix”),
(r”elche”,          “elche”),
(r”alicante.*centro”,“alicante centro”),
(r”alicante”,       “alicante”),
]
url_lower = url.lower()
for pattern, zone in patterns:
if re.search(pattern, url_lower):
return zone
return “default”

# ─────────────────────────────────────────────

# PERSISTENCIA DE IDs VISTOS (deduplicación)

# ─────────────────────────────────────────────

def load_seen_ids() -> set:
“”“Carga el conjunto de IDs de anuncios ya procesados.”””
if not os.path.exists(config.SEEN_IDS_FILE):
return set()
try:
with open(config.SEEN_IDS_FILE, “r”, encoding=“utf-8”) as f:
return set(json.load(f))
except Exception:
return set()

def save_seen_ids(seen_ids: set):
“”“Guarda el conjunto de IDs procesados.”””
ensure_output_dir()
with open(config.SEEN_IDS_FILE, “w”, encoding=“utf-8”) as f:
json.dump(list(seen_ids), f)

# ─────────────────────────────────────────────

# HISTÓRICO DE PRECIOS (bonus: detectar bajadas)

# ─────────────────────────────────────────────

def load_history() -> dict:
“”“Carga el historial de anuncios {id: [{‘fecha’: …, ‘precio’: …}]}.”””
if not os.path.exists(config.HISTORY_FILE):
return {}
try:
with open(config.HISTORY_FILE, “r”, encoding=“utf-8”) as f:
return json.load(f)
except Exception:
return {}

def save_history(history: dict):
“”“Guarda el historial actualizado.”””
ensure_output_dir()
with open(config.HISTORY_FILE, “w”, encoding=“utf-8”) as f:
json.dump(history, f, ensure_ascii=False, indent=2)

def update_price_history(history: dict, listing: dict) -> dict:
“””
Actualiza el historial de precios para un anuncio.
Devuelve info de cambio de precio: {‘bajada’: bool, ‘diferencia’: float}
“””
ad_id = listing.get(“id_anuncio”)
precio = listing.get(“precio”)
if not ad_id or precio is None:
return {“bajada”: False, “diferencia”: 0}

```
entry = {"fecha": listing.get("fecha_scraping"), "precio": precio}
change_info = {"bajada": False, "diferencia": 0, "precio_anterior": None}

if ad_id in history:
    registros = history[ad_id]
    if registros:
        ultimo_precio = registros[-1].get("precio")
        if ultimo_precio and precio < ultimo_precio:
            change_info["bajada"] = True
            change_info["diferencia"] = ultimo_precio - precio
            change_info["precio_anterior"] = ultimo_precio
            logger.info(
                f"⬇️  BAJADA DE PRECIO detectada en {ad_id}: "
                f"{ultimo_precio:,.0f}€ → {precio:,.0f}€ "
                f"(-{change_info['diferencia']:,.0f}€)"
            )
    history[ad_id].append(entry)
else:
    history[ad_id] = [entry]

return change_info
```

# ─────────────────────────────────────────────

# NOTIFICACIONES

# ─────────────────────────────────────────────

def send_telegram(message: str) -> bool:
“”“Envía mensaje a Telegram. Devuelve True si éxito.”””
if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
logger.warning(“Telegram no configurado (revisa .env).”)
return False
try:
url = f”https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage”
payload = {
“chat_id”: config.TELEGRAM_CHAT_ID,
“text”: message,
“parse_mode”: “HTML”,
“disable_web_page_preview”: False,
}
resp = requests.post(url, json=payload, timeout=10)
if resp.status_code == 200:
logger.info(“✅ Notificación Telegram enviada.”)
return True
else:
logger.error(f”Error Telegram: {resp.text}”)
return False
except Exception as e:
logger.error(f”Excepción enviando Telegram: {e}”)
return False

def send_email(subject: str, body: str) -> bool:
“”“Envía email con el lead. Devuelve True si éxito.”””
if not config.EMAIL_USER or not config.EMAIL_PASSWORD:
logger.warning(“Email no configurado (revisa .env).”)
return False
try:
msg = MIMEMultipart(“alternative”)
msg[“Subject”] = subject
msg[“From”]    = config.EMAIL_USER
msg[“To”]      = config.EMAIL_RECIPIENT
msg.attach(MIMEText(body, “html”, “utf-8”))

```
    with smtplib.SMTP(config.EMAIL_SMTP_HOST, config.EMAIL_SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.login(config.EMAIL_USER, config.EMAIL_PASSWORD)
        server.sendmail(config.EMAIL_USER, config.EMAIL_RECIPIENT, msg.as_string())
    logger.info("✅ Email enviado correctamente.")
    return True
except Exception as e:
    logger.error(f"Error enviando email: {e}")
    return False
```

def format_telegram_message(listing: dict, price_change: dict) -> str:
“”“Formatea un lead como mensaje Telegram HTML.”””
precio = f”{listing[‘precio’]:,.0f}€” if listing.get(“precio”) else “N/D”
m2     = f”{listing[‘m2’]:.0f}m²”     if listing.get(“m2”)    else “N/D”
epm2   = f”{listing[‘euro_m2’]:.0f}€/m²” if listing.get(“euro_m2”) else “N/D”
score  = f”{listing[‘score_particular’]:.2f}” if listing.get(“score_particular”) else “N/D”

```
bajada = ""
if price_change.get("bajada"):
    bajada = (
        f"\n⬇️ <b>BAJADA DE PRECIO:</b> -{price_change['diferencia']:,.0f}€ "
        f"(antes {price_change['precio_anterior']:,.0f}€)"
    )

return (
    f"🏠 <b>LEAD ALTA PRIORIDAD</b>\n"
    f"━━━━━━━━━━━━━━━━━━━━\n"
    f"📌 <b>{listing.get('titulo', 'Sin título')}</b>\n"
    f"📍 {listing.get('ubicacion', 'N/D')}\n"
    f"💶 {precio} | {m2} | {epm2}\n"
    f"🧍 Score particular: {score}\n"
    f"⭐ Oportunidad: {listing.get('oportunidad', 'N/D')}\n"
    f"📞 {listing.get('telefono', 'No disponible')}\n"
    f"{bajada}\n"
    f"🔗 <a href='{listing.get('url', '')}'>Ver anuncio</a>"
)
```

def format_email_body(listing: dict, price_change: dict) -> str:
“”“Formatea un lead como HTML para email.”””
precio = f”{listing[‘precio’]:,.0f}€” if listing.get(“precio”) else “N/D”
m2     = f”{listing[‘m2’]:.0f}m²”     if listing.get(“m2”)    else “N/D”
epm2   = f”{listing[‘euro_m2’]:.0f}€/m²” if listing.get(“euro_m2”) else “N/D”

```
bajada_html = ""
if price_change.get("bajada"):
    bajada_html = (
        f"<p style='color:green;'><b>⬇️ BAJADA DE PRECIO: "
        f"-{price_change['diferencia']:,.0f}€</b> "
        f"(precio anterior: {price_change['precio_anterior']:,.0f}€)</p>"
    )

return f"""
<html><body style="font-family:Arial,sans-serif;max-width:600px;margin:auto">
<h2 style="color:#e63946;">🏠 Lead Alta Prioridad — Idealista</h2>
<hr/>
<h3>{listing.get('titulo', 'Sin título')}</h3>
<p><b>📍 Ubicación:</b> {listing.get('ubicacion', 'N/D')}</p>
<p><b>💶 Precio:</b> {precio} &nbsp;|&nbsp; <b>Superficie:</b> {m2} &nbsp;|&nbsp; <b>€/m²:</b> {epm2}</p>
<p><b>🧍 Score particular:</b> {listing.get('score_particular', 'N/D'):.2f}</p>
<p><b>⭐ Oportunidad:</b> {listing.get('oportunidad', 'N/D')}</p>
<p><b>📞 Teléfono:</b> {listing.get('telefono', 'No disponible')}</p>
{bajada_html}
<p><a href="{listing.get('url','')}">🔗 Ver anuncio en Idealista</a></p>
<p><b>Descripción:</b><br/>{listing.get('descripcion', '')[:500]}...</p>
<hr/><small>Generado por Idealista Scraper — {listing.get('fecha_scraping','')}</small>
</body></html>
"""
```

def notify_high_priority(listing: dict, price_change: dict):
“”“Envía notificación del lead de alta prioridad por el canal configurado.”””
channel = config.NOTIFICATION_CHANNEL.lower()

```
if channel in ("telegram", "both"):
    msg = format_telegram_message(listing, price_change)
    send_telegram(msg)

if channel in ("email", "both"):
    subject = f"🏠 Lead Alta Prioridad: {listing.get('titulo','')[:60]}"
    body = format_email_body(listing, price_change)
    send_email(subject, body)
```
