import os
import json
import random
import requests
import re
from urllib.request import Request, urlopen
from fastapi import FastAPI, HTTPException, Request as FastAPIRequest, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from openai import OpenAI

app = FastAPI()

PENDING_APPROVALS = {}

class ShopifyCoffeeAgent:
    def __init__(self, shop_url, openai_api_key, client_id=None, client_secret=None, **kwargs):
        self.shop_url = shop_url.rstrip('/')
        self.ai_client = OpenAI(api_key=openai_api_key)
        
        self.client_id = client_id or os.getenv("SHOPIFY_CLIENT_ID") or os.getenv("SHOPIFY_API_KEY")
        self.client_secret = client_secret or os.getenv("SHOPIFY_CLIENT_SECRET") or os.getenv("SHOPIFY_API_SECRET")
        
        if not self.client_id or not self.client_secret:
            raise ValueError("[ERRORE CRITICO] Mancano SHOPIFY_CLIENT_ID o SHOPIFY_CLIENT_SECRET nelle variabili d'ambiente.")
        
        self.access_token = self._get_admin_access_token()

    def _get_admin_access_token(self):
        auth_url = self.shop_url + "/admin/oauth/access_token"
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "client_credentials"
        }
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        try:
            response = requests.post(auth_url, json=payload, headers=headers)
            if response.status_code == 200:
                data = response.json()
                token = data.get("access_token")
                if token:
                    return token
            raise Exception("Risposta Shopify " + str(response.status_code) + ": " + response.text)
        except Exception as e:
            raise Exception("Errore autenticazione OAuth Shopify: " + str(e))

    @property
    def headers(self):
        return {
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": self.access_token
        }

    def get_product_by_id(self, product_id):
        graphql_url = self.shop_url + "/admin/api/2024-07/graphql.json"
        numeric_id = str(product_id).split("/")[-1]
        gid = "gid://shopify/Product/" + numeric_id
        
        query = """
        query getProduct($id: ID!) {
          product(id: $id) {
            id
            title
            handle
            descriptionHtml
            tags
            variants(first: 20) {
              edges {
                node {
                  id
                  title
                  price
                  sku
                  selectedOptions {
                    name
                    value
                  }
                }
              }
            }
          }
        }
        """
        response = requests.post(graphql_url, json={"query": query, "variables": {"id": gid}}, headers=self.headers)
        if response.status_code == 200:
            data = response.json()
            node = data.get("data", {}).get("product")
            if not node:
                return None
            
            variants_list = []
            for v_edge in node.get("variants", {}).get("edges", []):
                v_node = v_edge.get("node", {})
                variants_list.append({
                    "id": v_node.get("id"),
                    "title": v_node.get("title"),
                    "price": v_node.get("price"),
                    "sku": v_node.get("sku"),
                    "options": v_node.get("selectedOptions", [])
                })

            return {
                "id": numeric_id,
                "title": node.get("title"),
                "handle": node.get("handle"),
                "body_html": node.get("descriptionHtml"),
                "tags": node.get("tags", []),
                "variants": variants_list
            }
        else:
            raise Exception("Errore di comunicazione con l'API GraphQL di Shopify: " + response.text)

    def get_all_products(self, limit=50):
        graphql_url = self.shop_url + "/admin/api/2024-07/graphql.json"
        query = """
        {
          products(first: 50, sortKey: UPDATED_AT, reverse: true) {
            edges {
              node {
                id
                title
                handle
                descriptionHtml
                tags
                productType
              }
            }
          }
        }
        """
        response = requests.post(graphql_url, json={"query": query}, headers=self.headers)
        if response.status_code == 200:
            data = response.json()
            edges = data.get("data", {}).get("products", {}).get("edges", [])
            products = []
            for edge in edges:
                node = edge.get("node", {})
                raw_id = node.get("id", "")
                numeric_id = raw_id.split("/")[-1] if raw_id else ""
                products.append({
                    "id": numeric_id,
                    "title": node.get("title"),
                    "handle": node.get("handle"),
                    "body_html": node.get("descriptionHtml"),
                    "product_type": node.get("productType"),
                    "tags": node.get("tags", [])
                })
            return products
        else:
            raise Exception("Errore di comunicazione con l'API GraphQL di Shopify: " + response.text)

    def scrape_url_content(self, url: str):
        try:
            req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(req, timeout=10) as response:
                html = response.read().decode('utf-8', errors='ignore')
            clean_html = re.sub(r'<script.*?>.*?</script>', '', html, flags=re.DOTALL)
            clean_html = re.sub(r'<style.*?>.*?</style>', '', clean_html, flags=re.DOTALL)
            text = re.sub(r'<[^>]+>', ' ', clean_html)
            return ' '.join(text.split())[:8000]
        except Exception as e:
            return f"Errore durante la lettura del link: {str(e)}"

    def parse_new_product_from_source(self, source_text: str, user_directive: str = ""):
        system_prompt = f"""Sei il maestro torrefattore ed esperto di marketing per Caffè Sansone di Napoli.
Analizza i dati grezzi e crea una scheda prodotto ottimizzata per Shopify.
DIRETTIVA: {user_directive or "Nessuna"}
Restituisci ESCLUSIVAMENTE un JSON con: title, body_html, tags, vendor ("Caffè Sansone"), product_type ("Caffè in Grani"), price, howto_schema."""
        try:
            response = self.ai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": source_text}],
                temperature=0.3,
                response_format={"type": "json_object"}
            )
            return json.loads(response.choices[0].message.content.strip())
        except Exception as e:
            raise Exception(f"Errore IA: {str(e)}")

    def create_shopify_product(self, product_data: dict):
        graphql_url = self.shop_url + "/admin/api/2024-07/graphql.json"
        mutation = """
        mutation productCreate($input: ProductInput!) {
          productCreate(input: $input) {
            product { id title handle }
            userErrors { field message }
          }
        }
        """
        tags_list = [t.strip() for t in product_data.get("tags", "").split(",") if t.strip()]
        if "Caffè Specialty" not in tags_list:
            tags_list.append("Caffè Specialty")

        input_data = {
            "title": product_data.get("title"),
            "descriptionHtml": product_data.get("body_html"),
            "vendor": product_data.get("vendor", "Caffè Sansone"),
            "productType": product_data.get("product_type", "Caffè in Grani"),
            "tags": tags_list,
            "variants": [{"price": product_data.get("price", "15.00"), "sku": f"SANSONE-{random.randint(1000,9999)}"}]
        }
        response = requests.post(graphql_url, json={"query": mutation, "variables": {"input": input_data}}, headers=self.headers)
        if response.status_code == 200:
            res_json = response.json()
            user_errors = res_json.get("data", {}).get("productCreate", {}).get("userErrors", [])
            if user_errors:
                raise Exception(f"Errore Shopify: {user_errors[0].get('message')}")
            return res_json.get("data", {}).get("productCreate", {}).get("product", {})
        raise Exception(f"Errore HTTP Shopify: {response.text}")

    def append_howto_to_product(self, product_data, user_directive=""):
        title = product_data.get("title")
        current_body = product_data.get("body_html", "") or ""
        system_prompt = f"Aggiungi un blocco HTML a scomparsa (details) con istruzioni di preparazione per {title}. DIRETTIVA: {user_directive or 'Nessuna'}. Restituisci JSON con 'body_html' e 'howto_schema'."
        try:
            response = self.ai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": current_body}],
                temperature=0.2,
                response_format={"type": "json_object"}
            )
            data = json.loads(response.choices[0].message.content.strip())
            if not data.get("body_html"):
                data["body_html"] = current_body
            return data
        except Exception:
            return {"body_html": current_body}

    def update_product_description_and_howto(self, product_id, update_data):
        graphql_url = self.shop_url + "/admin/api/2024-07/graphql.json"
        mutation = """
        mutation productUpdate($input: ProductInput!) {
          productUpdate(input: $input) {
            product { id title }
            userErrors { field message }
          }
        }
        """
        variables = {
            "input": {
                "id": "gid://shopify/Product/" + str(product_id),
                "descriptionHtml": update_data.get("body_html")
            }
        }
        response = requests.post(graphql_url, json={"query": mutation, "variables": variables}, headers=self.headers)
        return response.status_code == 200

    def suggest_merchandising_for_product(self, product_id, user_directive=""):
        target_prod = self.get_product_by_id(product_id)
        if not target_prod:
            raise Exception("Prodotto non trovato.")
        all_prods = self.get_all_products(limit=50)
        merch_candidates = [{"id": p["id"], "title": p["title"]} for p in all_prods if str(p["id"]) != str(target_prod["id"])]
        
        system_prompt = f"Seleziona 2 o 3 prodotti complementari dal catalogo per {target_prod['title']}. DIRETTIVA: {user_directive or 'Nessuna'}. Restituisci JSON con 'selected_ids' (array di ID) e 'merchandising_summary'."
        response = self.ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": json.dumps(merch_candidates)}],
            temperature=0.3,
            response_format={"type": "json_object"}
        )
        data = json.loads(response.choices[0].message.content.strip())
        return {
            "product_id": target_prod["id"],
            "title": target_prod["title"],
            "selected_ids": [str(x) for x in data.get("selected_ids", [])],
            "chosen_details": [p for p in merch_candidates if str(p["id"]) in [str(x) for x in data.get("selected_ids", [])]],
            "summary": data.get("merchandising_summary", "")
        }

    def update_product_merchandising_metafields(self, product_id, merch_ids):
        graphql_url = self.shop_url + "/admin/api/2024-07/graphql.json"
        owner_gid = "gid://shopify/Product/" + str(product_id)
        product_gids = ["gid://shopify/Product/" + str(m_id).split("/")[-1] for m_id in merch_ids]
        metafields_to_set = [{
            "ownerId": owner_gid,
            "namespace": "custom",
            "key": "complementary_products",
            "type": "list.product_reference",
            "value": json.dumps(product_gids)
        }]
        mutation = """
        mutation metafieldsSet($metafields: [MetafieldsSetInput!]!) {
          metafieldsSet(metafields: $metafields) {
            metafields { id }
            userErrors { field message }
          }
        }
        """
        response = requests.post(graphql_url, json={"query": mutation, "variables": {"metafields": metafields_to_set}}, headers=self.headers)
        return response.status_code == 200

    def get_creative_blog_ideas(self):
        try:
            response = self.ai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "system", "content": "Genera 4 spunti originali per il blog di Caffè Sansone. Restituisci JSON con chiave 'ideas' (array di oggetti con 'title' e 'angle')."}],
                temperature=0.7,
                response_format={"type": "json_object"}
            )
            return json.loads(response.choices[0].message.content.strip()).get("ideas", [])
        except Exception:
            return [{"title": "L'importanza dell'acqua nell'estrazione", "angle": "Focus chimico."}]

    def prepare_blog_post(self, topic: str, user_directive=""):
        system_prompt = f"Scrivi un articolo blog per Caffè Sansone. DIRETTIVA: {user_directive or 'Nessuna'}. Restituisci JSON con 'title', 'summary', 'body_html', 'tags'."
        response = self.ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": f"Argomento: {topic}"}],
            temperature=0.3,
            response_format={"type": "json_object"}
        )
        return json.loads(response.choices[0].message.content.strip())

    def publish_blog_post(self, blog_data: dict):
        graphql_url = self.shop_url + "/admin/api/2024-07/graphql.json"
        blogs_resp = requests.post(graphql_url, json={"query": "{ blogs(first: 1) { edges { node { id } } } }"}, headers=self.headers)
        blog_id = blogs_resp.json().get("data", {}).get("blogs", {}).get("edges", [])[0]["node"]["id"]
        mutation = """
        mutation articleCreate($article: ArticleCreateInput!, $blogId: ID!) {
          articleCreate(article: $article, blogId: $blogId) {
            article { id title }
            userErrors { field message }
          }
        }
        """
        variables = {
            "blogId": blog_id,
            "article": {
                "title": blog_data.get("title"),
                "bodyHtml": blog_data.get("body_html"),
                "summary": blog_data.get("summary"),
                "tags": [t.strip() for t in blog_data.get("tags", "").split(",") if t.strip()],
                "isPublished": True
            }
        }
        resp = requests.post(graphql_url, json={"query": mutation, "variables": variables}, headers=self.headers)
        return resp.json().get("data", {}).get("articleCreate", {}).get("article", {})
        shop_url = os.getenv("SHOP_URL", "https://348aca-2.myshopify.com")
openai_api_key = os.getenv("OPENAI_API_KEY", "")
client_id = os.getenv("SHOPIFY_CLIENT_ID", "")
client_secret = os.getenv("SHOPIFY_CLIENT_SECRET", "")

agent = ShopifyCoffeeAgent(shop_url=shop_url, openai_api_key=openai_api_key, client_id=client_id, client_secret=client_secret)

@app.get("/", response_class=HTMLResponse)
def read_root():
    ideas = agent.get_creative_blog_ideas()
    ideas_html = "".join([f'<div style="background: white; border: 1px solid #e1e4e8; padding: 12px; border-radius: 6px; margin-bottom: 10px; display: flex; justify-content: space-between; align-items: center;"><div><strong>{i.get("title")}</strong><br><span style="font-size: 12px; color: #666;">{i.get("angle")}</span></div><form action="/prepare-blog" method="post" style="margin: 0;"><input type="hidden" name="topic" value="{i.get("title")}"><button type="submit" style="background: #27ae60; color: white; border: none; padding: 8px 12px; border-radius: 4px; cursor: pointer; font-size: 12px; font-weight: bold;">Usa questo spunto</button></form></div>' for i in ideas])

    return f"""
    <html>
    <head><title>Caffè Sansone - AI Control Center</title>
    <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f4f6f8; color: #333; margin: 0; padding: 30px; }}
    .container {{ max-width: 900px; margin: auto; background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.05); }}
    h2 {{ color: #2c3e50; margin-top: 0; border-bottom: 2px solid #eaeaea; padding-bottom: 15px; }}
    .card {{ background: #fafbfc; padding: 20px; border-radius: 8px; margin-bottom: 25px; border: 1px solid #e1e4e8; }}
    label {{ display: block; margin-bottom: 8px; font-weight: 600; font-size: 14px; }}
    input[type='text'], textarea {{ width: 100%; padding: 10px; margin-bottom: 15px; border: 1px solid #d1d5db; border-radius: 6px; font-size: 14px; box-sizing: border-box; }}
    button {{ padding: 12px 20px; border: none; border-radius: 6px; cursor: pointer; font-size: 14px; font-weight: 600; }}
    .btn-primary {{ background: #2c3e50; color: white; }}
    </style>
    </head>
    <body>
    <div class="container">
    <h2>☕ Caffè Sansone - Dashboard Control Center</h2>
    
    <div class="card" style="border-left: 4px solid #8e44ad;">
    <h3>✨ 0. Crea e Ottimizza Nuovo Prodotto da Link</h3>
    <form action="/prepare-new-product" method="post">
    <label>Link scheda fornitore:</label>
    <input type="text" name="product_link" placeholder="https://..." required />
    <label>Direttiva personalizzata (opzionale):</label>
    <textarea name="user_directive" rows="2"></textarea>
    <button type="submit" class="btn-primary" style="background: #8e44ad;">🚀 Estrai e Crea</button>
    </form>
    </div>

    <div class="card">
    <h3>1. Inserimento HowTo per ID Prodotto Esistente</h3>
    <form action="/prepare-product-by-id" method="get">
    <label>ID Prodotto:</label>
    <input type="text" name="product_id" required />
    <label>Direttiva:</label>
    <textarea name="user_directive" rows="2"></textarea>
    <button type="submit" class="btn-primary">🔍 Genera HowTo</button>
    </form>
    </div>

    <div class="card">
    <h3>2. Suggerisci Merchandising (Metafield)</h3>
    <form action="/prepare-merchandising-by-id" method="get">
    <label>ID Prodotto Caffè:</label>
    <input type="text" name="product_id" required />
    <label>Direttiva:</label>
    <textarea name="user_directive" rows="2"></textarea>
    <button type="submit" class="btn-primary" style="background: #e67e22;">🎁 Suggerisci</button>
    </form>
    </div>

    <div class="card">
    <h3>3. Generatore Articoli Blog</h3>
    {ideas_html}
    <form action="/prepare-blog" method="post" style="margin-top: 15px;">
    <label>Argomento personalizzato:</label>
    <input type="text" name="topic" required />
    <label>Direttiva:</label>
    <textarea name="user_directive" rows="2"></textarea>
    <button type="submit" class="btn-primary" style="background: #27ae60;">✍️ Genera Bozza</button>
    </form>
    </div>

    </div></body></html>
    """

@app.post("/prepare-new-product", response_class=HTMLResponse)
def prepare_new_product(product_link: str = Form(...), user_directive: str = Form("")):
    try:
        scraped_text = agent.scrape_url_content(product_link)
        product_data = agent.parse_new_product_from_source(scraped_text, user_directive=user_directive)
        draft_id = f"new_prod_{random.randint(10000, 99999)}"
        PENDING_APPROVALS[draft_id] = {"type": "new_product", "data": product_data}
        return f"""<html><body style="font-family: Arial; padding: 30px;"><div style="max-width:900px; margin:auto;">
        <h2>✨ Revisione Nuovo Prodotto</h2>
        <h3>{product_data.get('title')}</h3>
        <p>Prezzo: € {product_data.get('price')} | Tag: {product_data.get('tags')}</p>
        <div style="background:#f9f9f9; padding:15px; border:1px solid #eee;">{product_data.get('body_html')}</div>
        <form action="/approve" method="post" style="margin-top:20px;"><input type="hidden" name="draft_id" value="{draft_id}"><button type="submit" style="background:#8e44ad; color:white; padding:10px 20px; border:none; border-radius:6px;">🚀 Approva e Crea su Shopify</button></form>
        <a href="/">Annulla</a></div></body></html>"""
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})

@app.get("/prepare-product-by-id", response_class=HTMLResponse)
def prepare_product_by_id(product_id: str, user_directive: str = ""):
    try:
        prod = agent.get_product_by_id(product_id)
        if not prod:
            return "<html><body>Prodotto non trovato! <a href='/'>Indietro</a></body></html>"
        update_data = agent.append_howto_to_product(prod, user_directive=user_directive)
        draft_id = f"prod_{product_id}"
        PENDING_APPROVALS[draft_id] = {"type": "product", "product_id": product_id, "data": update_data}
        return f"""<html><body style="font-family: Arial; padding: 30px;"><div style="max-width:900px; margin:auto;">
        <h2>📋 Revisione HowTo</h2><h3>{prod.get('title')}</h3>
        <div style="background:#f9f9f9; padding:15px; border:1px solid #eee;">{update_data.get('body_html')}</div>
        <form action="/approve" method="post" style="margin-top:20px;"><input type="hidden" name="draft_id" value="{draft_id}"><button type="submit" style="background:#10b981; color:white; padding:10px 20px; border:none; border-radius:6px;">✅ Approva e Aggiorna</button></form>
        <a href="/">Annulla</a></div></body></html>"""
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})

@app.get("/prepare-merchandising-by-id", response_class=HTMLResponse)
def prepare_merchandising_by_id(product_id: str, user_directive: str = ""):
    try:
        res = agent.suggest_merchandising_for_product(product_id, user_directive=user_directive)
        draft_id = f"merch_{product_id}"
        PENDING_APPROVALS[draft_id] = {"type": "merchandising", "product_id": product_id, "selected_ids": res.get("selected_ids")}
        items_li = "".join([f"<li>{item.get('title')}</li>" for item in res.get("chosen_details", [])])
        return f"""<html><body style="font-family: Arial; padding: 30px;"><div style="max-width:900px; margin:auto;">
        <h2>🎁 Revisione Merchandising</h2><h3>{res.get('title')}</h3>
        <p><b>Analisi:</b> {res.get('summary')}</p><ul>{items_li}</ul>
        <form action="/approve" method="post" style="margin-top:20px;"><input type="hidden" name="draft_id" value="{draft_id}"><button type="submit" style="background:#e67e22; color:white; padding:10px 20px; border:none; border-radius:6px;">✅ Salva Metafield</button></form>
        <a href="/">Annulla</a></div></body></html>"""
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})

@app.post("/prepare-blog", response_class=HTMLResponse)
def prepare_blog(topic: str = Form(...), user_directive: str = Form("")):
    try:
        blog_data = agent.prepare_blog_post(topic, user_directive=user_directive)
        draft_id = f"blog_{abs(hash(topic))}"
        PENDING_APPROVALS[draft_id] = {"type": "blog", "data": blog_data}
        return f"""<html><body style="font-family: Arial; padding: 30px;"><div style="max-width:900px; margin:auto;">
        <h2>✍️ Revisione Articolo Blog</h2><h3>{blog_data.get('title')}</h3>
        <p><b>Sommario:</b> {blog_data.get('summary')}</p>
        <div style="background:#f9f9f9; padding:15px; border:1px solid #eee;">{blog_data.get('body_html')}</div>
        <form action="/approve" method="post" style="margin-top:20px;"><input type="hidden" name="draft_id" value="{draft_id}"><button type="submit" style="background:#10b981; color:white; padding:10px 20px; border:none; border-radius:6px;">🚀 Approva e Pubblica</button></form>
        <a href="/">Annulla</a></div></body></html>"""
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})

@app.post("/approve", response_class=HTMLResponse)
def approve_draft(draft_id: str = Form(...)):
    if draft_id not in PENDING_APPROVALS:
        return "<html><body>Bozza scaduta o non trovata. <a href='/'>Torna alla Dashboard</a></body></html>"
    item = PENDING_APPROVALS.pop(draft_id)
    t = item.get("type")
    try:
        if t == "new_product":
            created = agent.create_shopify_product(item.get("data"))
            msg = f"Prodotto '{created.get('title')}' creato con successo!"
        elif t == "product":
            agent.update_product_description_and_howto(item.get("product_id"), item.get("data"))
            msg = "HowTo aggiunto con successo!"
        elif t == "merchandising":
            agent.update_product_merchandising_metafields(item.get("product_id"), item.get("selected_ids"))
            msg = "Metafield di merchandising salvati!"
        elif t == "blog":
            agent.publish_blog_post(item.get("data"))
            msg = "Articolo pubblicato con successo!"
        else:
            msg = "Operazione completata."
        return f"""<html><body style="font-family: Arial; padding: 40px; text-align: center;"><div style="max-width:600px; margin:auto; background:white; padding:30px; border-radius:12px;">
        <h2 style="color:#10b981;">Operazione riuscita!</h2><p>{msg}</p>
        <br><a href="/" style="background:#2c3e50; color:white; padding:10px 20px; text-decoration:none; border-radius:6px;">← Torna alla Dashboard</a>
        </div></body></html>"""
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})
