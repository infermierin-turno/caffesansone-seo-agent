import os
import json
import requests
from openai import OpenAI

class ShopifyCoffeeAgent:
    def __init__(self, shop_url: str, openai_api_key: str, client_id: str = None, client_secret: str = None):
        self.shop_url = shop_url.rstrip("/")
        self.openai_api_key = openai_api_key
        self.client_id = client_id
        self.client_secret = client_secret
        
        # Access token fisso o variabile d'ambiente Shopify Admin API
        self.access_token = os.getenv("SHOPIFY_ACCESS_TOKEN", "")
        self.headers = {
            "X-Shopify-Access-Token": self.access_token,
            "Content-Type": "application/json"
        }
        self.client_openai = OpenAI(api_key=self.openai_api_key)

    def get_pending_products(self, limit: int = 3):
        url = f"{self.shop_url}/admin/api/2024-07/products.json?limit=50&status=active"
        response = requests.get(url, headers=self.headers)
        if response.status_code != 200:
            return []
        
        products = response.json().get("products", [])
        pending = []
        for p in products:
            body = p.get("body_html", "") or ""
            # Se la descrizione è corta o non contiene i termini tipici dello specialty, lo consideriamo in sospeso
            if len(body) < 150 or "torrefazione" not in body.lower():
                pending.append({
                    "id": p.get("id"),
                    "title": p.get("title")
                })
            if len(pending) >= limit:
                break
        return pending

    def optimize_divise_content(self, title: str, current_body: str) -> dict:
        prompt = f"""
Sei un esperto di marketing del caffè specialty, copywriter SEO e torrefattore artigianale per caffesansone.it.
Devi ottimizzare la scheda prodotto per il seguente caffè:

Titolo attuale: {title}
Descrizione attuale: {current_body}

Crea contenuti in formato JSON rigoroso con le seguenti chiavi:
1. "seo_title": Un titolo SEO accattivante (max 60 caratteri) che includa il nome del caffè e termini legati a specialty coffee o torrefazione.
2. "seo_description": Una meta description persuasiva orientata alla conversione (max 155 caratteri).
3. "body_html": Una descrizione HTML formattata professionalmente che includa:
   - Un'introduzione accattivante sulla selezione dei chicchi e sulla tostatura artigianale a Napoli.
   - Un paragrafo sulle note aromatiche e sul profilo in tazza.
   - Consigli pratici sulla macinatura e sui metodi di estrazione ideali (espresso, filtro o cold brew).
   - Un richiamo alla freschezza e alla conservazione con valvola salvafreschezza.

Rispondi ESCLUSIVAMENTE in formato JSON valido, senza blocchi di codice markdown aggiuntivi se possibile, o comunque con una struttura JSON pulita e parsabile.
"""

        try:
            response = self.client_openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.3
            )
            content = response.choices[0].message.content.strip()
            return json.loads(content)
        except Exception as e:
            print(f"Errore nell'ottimizzazione IA: {e}")
            return {
                "seo_title": f"{title} | Caffè Specialty Artigianale",
                "seo_description": f"Scopri {title} su Caffè Sansone. Caffè monorigine e miscele tostate artigianalmente a Napoli per veri intenditori.",
                "body_html": f"<p><strong>{title}</strong> è un caffè specialty selezionato con cura e tostato artigianalmente nella nostra micro-torrefazione a Napoli.</p>"
            }
