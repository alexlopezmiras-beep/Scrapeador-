“””
scraper.py — Motor principal de scraping de Idealista.

Arquitectura:

- IdealistaScraper: gestiona sesión HTTP, parsea listados y detalle
- run(): orquesta el pipeline completo para todas las zonas
  “””

import json
import os
import re
import time
from datetime import datetime
from typing import Optional

import requests
from bs4 import BeautifulSoup, Tag

import config
import filters
from utils import (
ensure_output_dir,
fetch_url,
load_history,
load_seen_ids,
logger,
notify_high_priority,
parse_hours_since_publication,
parse_m2,
parse_price,
random_delay,
save_history,
save_seen_ids,
update_price_history,
extract_zone_from_url,
)

# ─────────────────────────────────────────────

# SCRAPER

# ─────────────────────────────────────────────

class IdealistaScraper:
“””
Scraper para Idealista.com.

```
Nota: Idealista carga muchos datos vía JS/React. Este scraper trabaja
con el HTML estático inicial (SSR) que contiene datos en JSON incrustados
(window.__INITIAL_PROPS__ o similares) y el markup HTML visible.
Para JS-heavy, se puede extender con Playwright (ver README).
"""

BASE_URL = "https://www.idealista.com"

def __init__(self):
    self.session = requests.Session()
    # Headers de sesión base (el UA se rota en cada request vía fetch_url)
    self.session.headers.update({
        "Referer": "https://www.idealista.com/",
        "Accept-Language": "es-ES,es;q=0.9",
    })

# ──────────────────────────────────────────
# LISTADO
# ──────────────────────────────────────────
def parse_listing_page(self, html: str, zona: str) -> list[dict]:
    """
    Parsea una página de resultados de Idealista.
    Intenta primero extraer JSON embebido (más fiable),
    luego cae a parseo HTML clásico.
    """
    listings = []

    # Intento 1: JSON embebido en el HTML (Idealista usa SSR con Next.js / custom)
    json_listings = self._extract_json_listings(html)
    if json_listings:
        logger.info(f"✅ Extraídos {len(json_listings)} anuncios via JSON embebido.")
        for item in json_listings:
            parsed = self._parse_json_item(item, zona)
            if parsed:
                listings.append(parsed)
        return listings

    # Intento 2: parseo HTML clásico
    logger.info("Usando parseo HTML clásico...")
    soup = BeautifulSoup(html, "lxml")
    articles = soup.find_all("article", class_=re.compile(r"item"))
    logger.info(f"Encontrados {len(articles)} artículos en HTML.")
    for article in articles:
        parsed = self._parse_html_article(article, zona)
        if parsed:
            listings.append(parsed)

    return listings

def _extract_json_listings(self, html: str) -> list:
    """
    Busca datos JSON incrustados en el HTML de Idealista.
    Idealista suele incluir datos en <script> con window.__INITIALPROPS__
    o en bloques JSON-LD / data attributes.
    """
    # Buscar JSON-LD de tipo ItemList
    soup = BeautifulSoup(html, "lxml")
    scripts = soup.find_all("script", type="application/ld+json")
    for script in scripts:
        try:
            data = json.loads(script.string or "")
            if isinstance(data, dict) and data.get("@type") == "ItemList":
                return data.get("itemListElement", [])
            if isinstance(data, list):
                return data
        except Exception:
            continue

    # Buscar en window.__INITIALPROPS__ u otros patrones
    patterns = [
        r'window\.__INITIAL_PROPS__\s*=\s*(\{.*?\});',
        r'"adList"\s*:\s*(\[.*?\])',
        r'"items"\s*:\s*(\[.*?\])',
    ]
    for pattern in patterns:
        match = re.search(pattern, html, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except Exception:
                continue

    return []

def _parse_json_item(self, item: dict, zona: str) -> Optional[dict]:
    """Convierte un item JSON de Idealista al formato estándar."""
    try:
        # Adaptamos según estructura real de Idealista
        ad_id = str(
            item.get("id") or
            item.get("adId") or
            item.get("propertyCode") or ""
        ).strip()
        if not ad_id:
            return None

        precio = parse_price(str(item.get("price", item.get("priceInfo", {}).get("amount", ""))))
        m2_raw = item.get("size") or item.get("rooms", {})
        m2     = float(m2_raw) if m2_raw and str(m2_raw).isdigit() else parse_m2(str(m2_raw))

        title    = item.get("title", item.get("suggestedTexts", {}).get("title", ""))
        desc     = item.get("description", item.get("fullDescription", ""))
        url_path = item.get("url", item.get("detailUrl", ""))
        url      = url_path if url_path.startswith("http") else f"{self.BASE_URL}{url_path}"

        # Anunciante
        advertiser = item.get("advertiser", item.get("contact", {}))
        if isinstance(advertiser, dict):
            name  = advertiser.get("name", advertiser.get("displayName", ""))
            ltype = advertiser.get("advertiserType", advertiser.get("type", ""))
        else:
            name  = str(advertiser)
            ltype = ""

        location = item.get("location", item.get("address", item.get("district", "")))
        if isinstance(location, dict):
            location = location.get("name", location.get("district", ""))

        time_text = item.get("newDevelopmentFinished", item.get("highlight", ""))

        return {
            "id_anuncio":        ad_id,
            "titulo":            title,
            "precio":            precio,
            "m2":                m2,
            "ubicacion":         location or zona,
            "descripcion":       desc,
            "nombre_anunciante": name,
            "tipo_anunciante":   ltype,
            "telefono":          None,
            "url":               url,
            "horas_publicacion": parse_hours_since_publication(str(time_text)),
            "fecha_scraping":    datetime.now().isoformat(timespec="seconds"),
            "zona_busqueda":     zona,
            "bajada_precio":     False,
        }
    except Exception as e:
        logger.debug(f"Error parseando JSON item: {e}")
        return None

def _parse_html_article(self, article: Tag, zona: str) -> Optional[dict]:
    """
    Parseo de fallback: extrae datos del HTML del article de Idealista.
    Compatible con el markup actual (2024-2025) pero puede requerir
    ajustes si Idealista cambia su HTML.
    """
    try:
        # ID del anuncio
        ad_id = article.get("data-element-id") or article.get("data-adid") or ""
        if not ad_id:
            # Intentar desde el link
            link_tag = article.find("a", href=True)
            if link_tag:
                m = re.search(r"/(\d+)\.htm", link_tag["href"])
                ad_id = m.group(1) if m else ""

        # URL
        link_tag = article.find("a", class_=re.compile(r"item-link|title-link"))
        if not link_tag:
            link_tag = article.find("a", href=re.compile(r"\.htm"))
        url = ""
        if link_tag and link_tag.get("href"):
            href = link_tag["href"]
            url  = href if href.startswith("http") else f"{self.BASE_URL}{href}"

        # Título
        title_tag = article.find(["h2", "h3"], class_=re.compile(r"item-title|title"))
        title = title_tag.get_text(strip=True) if title_tag else ""

        # Precio
        price_tag = article.find(class_=re.compile(r"item-price|price-row"))
        precio = parse_price(price_tag.get_text() if price_tag else "")

        # m²
        detail_tags = article.find_all(class_=re.compile(r"item-detail|feature"))
        m2 = None
        for tag in detail_tags:
            text = tag.get_text()
            if "m²" in text or "m2" in text.lower():
                m2 = parse_m2(text)
                break

        # Ubicación
        loc_tag = article.find(class_=re.compile(r"item-detail-location|location|address"))
        ubicacion = loc_tag.get_text(strip=True) if loc_tag else zona

        # Descripción
        desc_tag = article.find(class_=re.compile(r"item-description|description"))
        descripcion = desc_tag.get_text(strip=True) if desc_tag else ""

        # Tiempo publicación
        time_tag = article.find(class_=re.compile(r"item-date|date|time"))
        horas = parse_hours_since_publication(time_tag.get_text() if time_tag else "")

        # Anunciante (a veces no está en el listado, se obtiene en detalle)
        adv_tag = article.find(class_=re.compile(r"advertiser|agency|contact"))
        nombre_anunciante = adv_tag.get_text(strip=True) if adv_tag else ""
        tipo_anunciante   = ""

        return {
            "id_anuncio":        ad_id,
            "titulo":            title,
            "precio":            precio,
            "m2":                m2,
            "ubicacion":         ubicacion,
            "descripcion":       descripcion,
            "nombre_anunciante": nombre_anunciante,
            "tipo_anunciante":   tipo_anunciante,
            "telefono":          None,
            "url":               url,
            "horas_publicacion": horas,
            "fecha_scraping":    datetime.now().isoformat(timespec="seconds"),
            "zona_busqueda":     zona,
            "bajada_precio":     False,
        }

    except Exception as e:
        logger.debug(f"Error parseando artículo HTML: {e}")
        return None

# ──────────────────────────────────────────
# DETALLE DEL ANUNCIO
# ──────────────────────────────────────────
def enrich_from_detail(self, listing: dict) -> dict:
    """
    Visita la página de detalle del anuncio para obtener:
    - descripción completa
    - nombre/tipo de anunciante
    - teléfono (si está visible antes de login)
    """
    if not listing.get("url"):
        return listing

    html = fetch_url(listing["url"], self.session)
    if not html:
        return listing

    soup = BeautifulSoup(html, "lxml")

    # Descripción completa
    desc_tag = soup.find(class_=re.compile(r"comment|description|adCommentsLanguage"))
    if desc_tag and len(desc_tag.get_text(strip=True)) > len(listing.get("descripcion", "")):
        listing["descripcion"] = desc_tag.get_text(strip=True)

    # Nombre y tipo de anunciante
    adv_name_tag = soup.find(class_=re.compile(r"advertiser-name|agency-name|contact-name"))
    if adv_name_tag and not listing.get("nombre_anunciante"):
        listing["nombre_anunciante"] = adv_name_tag.get_text(strip=True)

    adv_type_tag = soup.find(class_=re.compile(r"advertiser-type|advertiser-badge"))
    if adv_type_tag:
        listing["tipo_anunciante"] = adv_type_tag.get_text(strip=True)

    # Teléfono (visible en algunos casos sin JS)
    phone_tag = soup.find(class_=re.compile(r"phone|telefono|contact-phone"))
    if phone_tag:
        phone_text = phone_tag.get_text()
        phone_match = re.search(r"\b[6789]\d{8}\b", phone_text)
        if phone_match:
            listing["telefono"] = phone_match.group(0)

    # Buscar teléfono en toda la descripción (particulares a veces lo ponen)
    if not listing.get("telefono"):
        full_text = soup.get_text()
        phone_match = re.search(r"\b[6789]\d{8}\b", full_text)
        if phone_match:
            listing["telefono"] = phone_match.group(0)

    # m² si falta
    if not listing.get("m2"):
        chars_tag = soup.find(class_=re.compile(r"info-features|characteristics|features"))
        if chars_tag:
            listing["m2"] = parse_m2(chars_tag.get_text())

    return listing

# ──────────────────────────────────────────
# PAGINACIÓN
# ──────────────────────────────────────────
def get_next_page_url(self, html: str, current_url: str) -> Optional[str]:
    """Extrae URL de la siguiente página de resultados."""
    soup = BeautifulSoup(html, "lxml")
    next_tag = soup.find("a", class_=re.compile(r"pagination-next|next"))
    if not next_tag:
        next_tag = soup.find("a", rel="next")
    if next_tag and next_tag.get("href"):
        href = next_tag["href"]
        return href if href.startswith("http") else f"{self.BASE_URL}{href}"
    return None

# ──────────────────────────────────────────
# SCRAPING DE UNA ZONA
# ──────────────────────────────────────────
def scrape_zone(
    self,
    start_url: str,
    seen_ids: set,
    history: dict,
    max_pages: int = 3,
) -> tuple[list[dict], set, dict]:
    """
    Itera por páginas de una zona, aplica filtros y enriquece anuncios.
    Retorna (nuevos_listings, seen_ids_actualizado, history_actualizado)
    """
    zona    = extract_zone_from_url(start_url)
    results = []
    url     = start_url
    page    = 1

    logger.info(f"\n{'═'*60}")
    logger.info(f"🔍 Zona: {zona.upper()} | Inicio: {start_url[:70]}")
    logger.info(f"{'═'*60}")

    while url and page <= max_pages:
        logger.info(f"📄 Página {page}/{max_pages} — {url[:70]}")
        html = fetch_url(url, self.session)
        if not html:
            logger.error(f"No se pudo descargar la página {page}.")
            break

        listings_raw = self.parse_listing_page(html, zona)
        logger.info(f"  → {len(listings_raw)} anuncios encontrados en esta página.")

        new_count = 0
        for listing in listings_raw:
            ad_id = listing.get("id_anuncio")
            if not ad_id:
                continue

            # Deduplicación
            if ad_id in seen_ids:
                logger.debug(f"  ↪ Duplicado: {ad_id}")
                continue

            # Enriquecer desde página de detalle (con delay)
            random_delay()
            listing = self.enrich_from_detail(listing)

            # Filtros y scores
            listing = filters.enrich_listing(listing, zona)

            # Histórico de precios
            price_change = update_price_history(history, listing)
            listing["bajada_precio"]     = price_change["bajada"]
            listing["precio_anterior"]   = price_change.get("precio_anterior")
            listing["bajada_diferencia"] = price_change.get("diferencia", 0)

            # Recalcular prioridad con info de bajada
            listing["prioridad"] = filters.compute_priority(listing)

            seen_ids.add(ad_id)
            results.append(listing)
            new_count += 1

            score = listing["score_particular"]
            prio  = listing["prioridad"]
            oport = listing["oportunidad"]
            logger.info(
                f"  ✓ [{prio.upper()}] {listing.get('titulo','')[:50]} | "
                f"Score: {score:.2f} | {oport} | "
                f"{listing.get('precio',0):,.0f}€"
            )

            # Notificar si alta prioridad
            if prio == "alta":
                notify_high_priority(listing, price_change)

        logger.info(f"  → {new_count} anuncios NUEVOS procesados en página {page}.")

        # Siguiente página
        next_url = self.get_next_page_url(html, url)
        if next_url and next_url != url:
            url = next_url
            page += 1
            random_delay()
        else:
            logger.info("  → No hay más páginas.")
            break

    return results, seen_ids, history
```

# ─────────────────────────────────────────────

# OUTPUT

# ─────────────────────────────────────────────

def save_results(listings: list[dict]):
“”“Guarda resultados en CSV y JSON.”””
import csv
ensure_output_dir()

```
if not listings:
    logger.info("No hay nuevos anuncios que guardar.")
    return

# ── JSON ──────────────────────────────────
existing = []
if os.path.exists(config.JSON_FILE):
    try:
        with open(config.JSON_FILE, "r", encoding="utf-8") as f:
            existing = json.load(f)
    except Exception:
        pass

all_listings = existing + listings
with open(config.JSON_FILE, "w", encoding="utf-8") as f:
    json.dump(all_listings, f, ensure_ascii=False, indent=2)
logger.info(f"💾 JSON guardado: {config.JSON_FILE} ({len(all_listings)} registros totales)")

# ── CSV ───────────────────────────────────
fields = [
    "fecha_scraping", "id_anuncio", "titulo", "precio", "m2", "euro_m2",
    "ubicacion", "nombre_anunciante", "tipo_anunciante", "telefono",
    "url", "score_particular", "oportunidad", "prioridad",
    "horas_publicacion", "bajada_precio", "precio_anterior",
    "bajada_diferencia", "zona_busqueda",
]
file_exists = os.path.exists(config.CSV_FILE)
with open(config.CSV_FILE, "a", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
    if not file_exists:
        writer.writeheader()
    writer.writerows(listings)
logger.info(f"💾 CSV guardado: {config.CSV_FILE} (+{len(listings)} filas)")
```

def print_summary(listings: list[dict]):
“”“Muestra resumen de los leads encontrados.”””
if not listings:
logger.info(”\n📊 Sin nuevos anuncios en este ciclo.”)
return

```
alta   = [l for l in listings if l.get("prioridad") == "alta"]
media  = [l for l in listings if l.get("prioridad") == "media"]
baja   = [l for l in listings if l.get("prioridad") == "baja"]
bajadas = [l for l in listings if l.get("bajada_precio")]

logger.info("\n" + "═"*60)
logger.info(f"📊 RESUMEN DEL CICLO — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
logger.info("═"*60)
logger.info(f"  Total anuncios procesados : {len(listings)}")
logger.info(f"  🔴 Alta prioridad         : {len(alta)}")
logger.info(f"  🟡 Media prioridad        : {len(media)}")
logger.info(f"  🟢 Baja prioridad         : {len(baja)}")
logger.info(f"  ⬇️  Con bajada de precio   : {len(bajadas)}")
logger.info("═"*60)

if alta:
    logger.info("\n🔴 LEADS DE ALTA PRIORIDAD:")
    for l in alta:
        precio = f"{l.get('precio',0):,.0f}€" if l.get("precio") else "N/D"
        logger.info(
            f"  → {l.get('titulo','')[:50]} | {precio} | "
            f"Score: {l.get('score_particular',0):.2f} | {l.get('url','')[:60]}"
        )
```

# ─────────────────────────────────────────────

# PUNTO DE ENTRADA

# ─────────────────────────────────────────────

def run(max_pages_per_zone: int = 3):
“””
Ejecuta el pipeline completo:
1. Carga estado previo (IDs vistos, histórico)
2. Scraping de todas las zonas configuradas
3. Guarda resultados y estado
4. Muestra resumen
“””
logger.info(”\n” + “█”*60)
logger.info(f”  🏠 IDEALISTA SCRAPER — Inicio: {datetime.now().strftime(’%Y-%m-%d %H:%M:%S’)}”)
logger.info(“█”*60)

```
ensure_output_dir()
seen_ids = load_seen_ids()
history  = load_history()
scraper  = IdealistaScraper()
all_new  = []

for url in config.SEARCH_URLS:
    try:
        new_listings, seen_ids, history = scraper.scrape_zone(
            url, seen_ids, history, max_pages=max_pages_per_zone
        )
        all_new.extend(new_listings)
        # Delay entre zonas
        time.sleep(15)
    except Exception as e:
        logger.error(f"Error crítico scrapeando {url}: {e}", exc_info=True)
        continue

# Persistir estado
save_seen_ids(seen_ids)
save_history(history)
save_results(all_new)
print_summary(all_new)

logger.info(f"\n✅ Ciclo completado. Total nuevos anuncios: {len(all_new)}")
return all_new
```

if **name** == “**main**”:
run()
