“””
filters.py — Detección de particulares, scoring y clasificación de oportunidades.
“””

import re
from typing import Optional

import config
from utils import logger

# ─────────────────────────────────────────────

# HELPERS

# ─────────────────────────────────────────────

def _normalize(text: str) -> str:
“”“Normaliza texto: minúsculas, sin tildes, sin puntuación extra.”””
if not text:
return “”
t = text.lower()
replacements = {
“á”: “a”, “é”: “e”, “í”: “i”, “ó”: “o”, “ú”: “u”,
“ü”: “u”, “ñ”: “n”,
}
for orig, rep in replacements.items():
t = t.replace(orig, rep)
return t

def _contains_any(text: str, keywords: list) -> bool:
“”“Comprueba si el texto contiene alguna de las palabras clave.”””
norm = _normalize(text)
return any(kw in norm for kw in keywords)

def _count_keywords(text: str, keywords: list) -> int:
“”“Cuenta cuántas palabras clave aparecen en el texto.”””
norm = _normalize(text)
return sum(1 for kw in keywords if kw in norm)

# ─────────────────────────────────────────────

# A) REGLAS DURAS

# ─────────────────────────────────────────────

def rule_is_agency(advertiser_name: str, description: str, listing_type: str) -> bool:
“””
Retorna True si hay indicios claros de agencia inmobiliaria.
Descarta el anuncio.
“””
combined = f”{advertiser_name} {description} {listing_type}”
if _contains_any(combined, config.KEYWORDS_AGENCY):
return True
# Patrón: nombre con S.L., S.A., etc.
if re.search(r”\b(s.?l.?|s.?a.?|slp|slne)\b”, _normalize(advertiser_name)):
return True
return False

def rule_is_particular(advertiser_name: str, description: str, listing_type: str) -> bool:
“””
Retorna True si hay indicios directos de particular.
“””
combined = f”{advertiser_name} {description} {listing_type}”
if _contains_any(combined, config.KEYWORDS_PARTICULAR):
return True
return False

def rule_name_is_person(name: str) -> bool:
“””
Heurística: el nombre del anunciante parece una persona real.
Criterios:
- Contiene 1-3 palabras (nombre + apellido/s)
- Al menos una coincide con nombres comunes españoles
- No contiene palabras de empresa
“””
if not name:
return False
norm = _normalize(name.strip())
words = norm.split()
if not (1 <= len(words) <= 4):
return False
if _contains_any(norm, config.KEYWORDS_AGENCY):
return False
# Al menos una palabra coincide con nombre común
for word in words:
if word in config.COMMON_NAMES_ES:
return True
return False

# ─────────────────────────────────────────────

# B) HEURÍSTICAS DE LENGUAJE

# ─────────────────────────────────────────────

def heuristic_emotional_language(description: str) -> float:
“””
Puntúa del 0 al 1 según presencia de lenguaje emocional/personal.
Más score → más probable particular.
“””
count = _count_keywords(description, config.EMOTIONAL_KEYWORDS)
# Máximo esperado ~5 palabras emocionales
return min(count / 5.0, 1.0)

def heuristic_commercial_language(description: str) -> float:
“””
Puntúa del 0 al 1 según presencia de lenguaje comercial/agencia.
Más score → más probable agencia (penaliza score_particular).
“””
count = _count_keywords(description, config.COMMERCIAL_KEYWORDS)
return min(count / 4.0, 1.0)

def heuristic_description_length(description: str) -> float:
“””
Descripciones muy cortas (<80 chars) o muy largas (>1500 chars) suelen ser agencias.
Descripción de longitud media típica de particular.
“””
length = len(description.strip())
if 80 <= length <= 800:
return 0.6
elif 800 < length <= 1500:
return 0.3
else:
return 0.0

def heuristic_phone_in_description(description: str) -> float:
“””
Teléfono en la descripción → señal de particular (más informal).
“””
if re.search(r”\b[6789]\d{8}\b”, description):
return 0.3
return 0.0

def heuristic_first_person(description: str) -> float:
“””
Uso de primera persona → probable particular hablando de su casa.
“””
patterns_first_person = [
r”\bvendo\b”, r”\bnuestra\b”, r”\bnuestro\b”, r”\bmi (piso|casa|apartamento|vivienda)\b”,
r”\bme mudo\b”, r”\bnos mudamos\b”, r”\bhe reformado\b”, r”\bhemos reformado\b”,
r”\bhe vivido\b”, r”\bvivimos\b”,
]
norm = _normalize(description)
count = sum(1 for p in patterns_first_person if re.search(p, norm))
return min(count / 3.0, 0.5)

# ─────────────────────────────────────────────

# C) SCORE FINAL

# ─────────────────────────────────────────────

def compute_particular_score(
advertiser_name: str,
description: str,
listing_type: str,
) -> float:
“””
Calcula score_particular (0.0 → agencia segura, 1.0 → particular seguro).

```
Lógica en capas:
1. Reglas duras (cortocircuito)
2. Heurísticas ponderadas
"""
desc = description or ""
name = advertiser_name or ""
ltype = listing_type or ""

# ── Reglas duras ──────────────────────────
if rule_is_agency(name, desc, ltype):
    return 0.05  # casi seguro agencia

base_score = 0.4  # neutro

if rule_is_particular(name, desc, ltype):
    base_score += 0.35

if rule_name_is_person(name):
    base_score += 0.20

# ── Heurísticas ───────────────────────────
emotional    = heuristic_emotional_language(desc)
commercial   = heuristic_commercial_language(desc)
length_score = heuristic_description_length(desc)
phone_score  = heuristic_phone_in_description(desc)
first_person = heuristic_first_person(desc)

# Pesos
heuristic_bonus = (
    emotional    * 0.15 +
    length_score * 0.05 +
    phone_score  * 0.10 +
    first_person * 0.10
)
heuristic_penalty = commercial * 0.25

score = base_score + heuristic_bonus - heuristic_penalty

# Clamp [0.0, 1.0]
return round(max(0.0, min(1.0, score)), 3)
```

# ─────────────────────────────────────────────

# DETECCIÓN DE OPORTUNIDADES

# ─────────────────────────────────────────────

def classify_opportunity(precio: Optional[float], m2: Optional[float], zona: str) -> str:
“””
Compara el precio €/m² con la media estimada de mercado.
Retorna: ‘alta’, ‘media’, ‘baja’, o ‘sin datos’
“””
if not precio or not m2 or m2 <= 0:
return “sin datos”

```
euro_m2 = precio / m2
media   = config.MARKET_PRICES.get(zona, config.MARKET_PRICES["default"])
diff    = (media - euro_m2) / media  # fracción por debajo del mercado

if diff >= config.OPPORTUNITY_HIGH:
    return "alta"
elif diff >= config.OPPORTUNITY_MEDIUM:
    return "media"
else:
    return "baja"
```

def compute_euro_m2(precio: Optional[float], m2: Optional[float]) -> Optional[float]:
“”“Calcula precio por metro cuadrado.”””
if precio and m2 and m2 > 0:
return round(precio / m2, 1)
return None

# ─────────────────────────────────────────────

# PRIORIDAD GLOBAL DEL LEAD

# ─────────────────────────────────────────────

def compute_priority(listing: dict) -> str:
“””
Clasifica prioridad del lead: ‘alta’, ‘media’, ‘baja’.

```
Alta si:
  - Es anuncio nuevo (<48h) AND
  - Score particular alto (>0.7) AND
  - Oportunidad alta o media

Media si:
  - Score particular >0.5 OR
  - Oportunidad alta

Baja en el resto.
"""
hours = listing.get("horas_publicacion")
score = listing.get("score_particular", 0)
oport = listing.get("oportunidad", "baja")
bajada = listing.get("bajada_precio", False)

is_new     = hours is not None and hours <= config.PRIORITY_MAX_HOURS
is_part    = score >= config.SCORE_PARTICULAR_HIGH
is_opport  = oport in ("alta", "media")

if (is_new and is_part and is_opport) or bajada:
    return "alta"
elif (score >= 0.5 and is_opport) or (is_new and is_part):
    return "media"
else:
    return "baja"
```

# ─────────────────────────────────────────────

# PIPELINE COMPLETO SOBRE UN LISTING

# ─────────────────────────────────────────────

def enrich_listing(listing: dict, zona: str) -> dict:
“””
Aplica todos los filtros y scores a un listing raw.
Añade: score_particular, oportunidad, euro_m2, prioridad.
“””
name  = listing.get(“nombre_anunciante”, “”)
desc  = listing.get(“descripcion”, “”)
ltype = listing.get(“tipo_anunciante”, “”)

```
listing["score_particular"] = compute_particular_score(name, desc, ltype)
listing["euro_m2"]          = compute_euro_m2(listing.get("precio"), listing.get("m2"))
listing["oportunidad"]      = classify_opportunity(
    listing.get("precio"), listing.get("m2"), zona
)
listing["prioridad"]        = compute_priority(listing)

return listing
```
