“””
config.py — Configuración central del sistema de scraping inmobiliario.
Carga variables desde .env y define parámetros globales.
“””

import os
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────

# URLS DE BÚSQUEDA (añade/quita zonas aquí)

# ─────────────────────────────────────────────

SEARCH_URLS = [
# Elche — venta pisos particulares
“https://www.idealista.com/venta-viviendas/elche-alicante/con-precio-hasta_200000/?ordenado-por=fecha-publicacion-desc”,
# Alicante — venta pisos particulares
“https://www.idealista.com/venta-viviendas/alicante-alicante/con-precio-hasta_300000/?ordenado-por=fecha-publicacion-desc”,
# Alicante Centro
“https://www.idealista.com/venta-viviendas/alicante-alicante/centro/?ordenado-por=fecha-publicacion-desc”,
# Elche Altabix
“https://www.idealista.com/venta-viviendas/elche-alicante/altabix/?ordenado-por=fecha-publicacion-desc”,
]

# ─────────────────────────────────────────────

# ANTI-BLOQUEO

# ─────────────────────────────────────────────

DELAY_MIN = 8          # segundos mínimos entre peticiones
DELAY_MAX = 20         # segundos máximos entre peticiones
MAX_RETRIES = 3        # reintentos por URL fallida
RETRY_WAIT = 30        # segundos entre reintentos
REQUEST_TIMEOUT = 20   # timeout por petición HTTP

USER_AGENTS = [
“Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36”,
“Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15”,
“Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0”,
“Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36”,
“Mozilla/5.0 (Macintosh; Intel Mac OS X 13_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36”,
“Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1”,
]

# ─────────────────────────────────────────────

# PRECIOS MEDIOS €/m² POR ZONA (estimados)

# Actualiza estos valores con datos reales de mercado

# ─────────────────────────────────────────────

MARKET_PRICES = {
“elche”:            1_350,
“alicante”:         1_900,
“alicante centro”:  2_200,
“elche altabix”:    1_400,
“default”:          1_600,
}

# Umbrales para clasificar oportunidad (% bajo precio de mercado)

OPPORTUNITY_HIGH   = 0.20   # >20% bajo mercado → alta oportunidad
OPPORTUNITY_MEDIUM = 0.10   # >10% bajo mercado → media oportunidad

# ─────────────────────────────────────────────

# FILTROS DE PRIORIDAD

# ─────────────────────────────────────────────

PRIORITY_MAX_HOURS    = 48   # anuncios con menos de N horas → nuevos
SCORE_PARTICULAR_HIGH = 0.7  # umbral score para considerar “probable particular”

# ─────────────────────────────────────────────

# PALABRAS CLAVE PARA DETECCIÓN

# ─────────────────────────────────────────────

KEYWORDS_AGENCY = [
“inmobiliaria”, “real estate”, “properties”, “grupo”, “ api “,
“gestión”, “gestion”, “consultores”, “asesores”, “realty”,
“agencia”, “agency”, “servicios inmobiliarios”, “s.l.”, “s.a.”,
“sl “, “ sl,”, “sociedad”, “inversiones”, “capital”, “holding”,
“pisos.com”, “idealista”, “habitaclia”, “fotocasa”,
]

KEYWORDS_PARTICULAR = [
“particular”, “propietario”, “dueño”, “dueno”, “vendo mi”,
“vendo piso”, “vendo casa”, “vendo apartamento”, “sin intermediarios”,
“sin comisiones”, “trato directo”, “vendo por”,
]

EMOTIONAL_KEYWORDS = [
“encantador”, “precioso”, “luminoso”, “acogedor”, “familiar”,
“tranquilo”, “reformado por”, “vivimos”, “nuestra casa”,
“con cariño”, “con carino”, “hemos reformado”, “nos mudamos”,
“años en”, “recuerdos”, “hogar”, “jardín privado”,
]

COMMERCIAL_KEYWORDS = [
“rentabilidad”, “inversión”, “roi”, “cartera”, “portfolio”,
“gestión integral”, “exclusiva”, “mandato”, “honorarios”,
“comisión”, “comision”, “nuestros clientes”, “nuestra cartera”,
“visita virtual”, “tour 360”, “nota simple incluida”,
]

COMMON_NAMES_ES = [
“juan”, “maria”, “jose”, “antonio”, “manuel”, “francisco”, “david”,
“pedro”, “carlos”, “miguel”, “jesus”, “rafael”, “jorge”, “daniel”,
“alejandro”, “luis”, “javier”, “fernando”, “pablo”, “ana”, “laura”,
“marta”, “carmen”, “rosa”, “isabel”, “elena”, “sofia”, “lucia”,
“sara”, “paula”, “patricia”, “cristina”, “raquel”, “beatriz”,
“pilar”, “dolores”, “concepcion”, “amparo”, “inmaculada”, “gloria”,
]

# ─────────────────────────────────────────────

# NOTIFICACIONES — cargadas desde .env

# ─────────────────────────────────────────────

TELEGRAM_BOT_TOKEN = os.getenv(“TELEGRAM_BOT_TOKEN”, “”)
TELEGRAM_CHAT_ID   = os.getenv(“TELEGRAM_CHAT_ID”, “”)

EMAIL_SMTP_HOST    = os.getenv(“EMAIL_SMTP_HOST”, “smtp.gmail.com”)
EMAIL_SMTP_PORT    = int(os.getenv(“EMAIL_SMTP_PORT”, “587”))
EMAIL_USER         = os.getenv(“EMAIL_USER”, “”)
EMAIL_PASSWORD     = os.getenv(“EMAIL_PASSWORD”, “”)
EMAIL_RECIPIENT    = os.getenv(“EMAIL_RECIPIENT”, “”)

# Activa el canal que prefieras: “telegram” | “email” | “both” | “none”

NOTIFICATION_CHANNEL = os.getenv(“NOTIFICATION_CHANNEL”, “telegram”)

# ─────────────────────────────────────────────

# RUTAS DE SALIDA

# ─────────────────────────────────────────────

OUTPUT_DIR      = “output”
CSV_FILE        = os.path.join(OUTPUT_DIR, “leads.csv”)
JSON_FILE       = os.path.join(OUTPUT_DIR, “leads.json”)
HISTORY_FILE    = os.path.join(OUTPUT_DIR, “history.json”)
SEEN_IDS_FILE   = os.path.join(OUTPUT_DIR, “seen_ids.json”)

# ─────────────────────────────────────────────

# PROXY (opcional — descomenta y configura)

# ─────────────────────────────────────────────

# PROXIES = {

# “http”:  os.getenv(“PROXY_HTTP”, “”),

# “https”: os.getenv(“PROXY_HTTPS”, “”),

# }

PROXIES = None
