import os
import json
import requests
from fastapi import FastAPI, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from openai import OpenAI

app = FastAPI()

# Memoria temporanea in-memory per le bozze in attesa di approvazione
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
        auth_url = f"{self.shop_url}/admin/oauth/access_token"
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
            raise Exception(f"Risposta Shopify {response.status_code}: {response.text}")
        except Exception as e:
            raise Exception(f"Errore autenticazione OAuth Shopify: {e}")

    @property
    def headers(self):
        return {
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": self.access_token
        }

    def get_products(self, limit=50):
        graphql_url = f"{self.shop_url}/admin/api/2024-07/graphql.json"
        query = f"""
        {{
          products(first: {limit}) {{
            edges {{
              node {{
                id
                title
                handle
                descriptionHtml
                tags
                variants(first: 20) {{
                  edges {{
                    node {{
                      id
                      title
                      price
                      sku
                      selectedOptions {{
                        name
                        value
                      }}
                    }}
                  }}
                }}
              }}
            }}
          }}
        }}
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

                products.append({
                    "id": numeric_id,
                    "title": node.get("title"),
                    "body_html": node.get("descriptionHtml"),
                    "tags": node.get("tags", []),
                    "variants": variants_list
                })
            return products
        else:
            raise Exception(f"Errore di comunicazione con l'API GraphQL di Shopify: {response.text}")

    def optimize_coffee_content(self, product_data_or_title, current_body=None, variants=None):
        if isinstance(product_data_or_title, dict):
            product_data = product_data_or_title
        else:
            product_data = {
                "title": product_data_or_title,
                "body_html": current_body,
                "variants": variants or []
            }

        title = product_data.get("title")
        body = product_data.get("body_html", "") or ""
        var_list = product_data.get("variants", [])

        system_prompt = """Sei un maestro torrefattore ed esperto di caffè specialty, micro-torrefazione artigianale e metodi di estrazione avanzati per Caffè Sansone.

Scrivi descrizioni avvincenti, competenti e orientate all'eccellenza per un e-commerce di caffè d'alta qualità. La voce del brand è autorevole, appassionata, trasparente e focalizzata sulla tracciabilità e sulla qualità in tazza.

Metti in evidenza:
- profilo aromatico, note di degustazione e origine dei chicchi;
- metodo di lavorazione (es. lavato, naturale, honey) se presente;
- grado di macinatura o formato in chicchi;
- consigli specifici per l'estrazione ottimale (temperatura dell'acqua, ratio, macchine consigliate come espresso, moka, filtro V60, aeropress o cold brew);
- la freschezza della micro-torrefazione artigianale napoletana.

REGOLA FONDAMENTALE SUI LINK E DATI:
Non inventare mai caratteristiche, origini, altitudini, varietà botaniche o note sensoriali non presenti nelle informazioni fornite. Se un dato non è disponibile, omettilo con eleganza.

La descrizione HTML deve essere ordinata e pulita:
- un'introduzione coinvolgente con <p>;
- titoli <h2> descrittivi (es. Profilo Aromatico, Consigli di Estrazione);
- elenchi puntati con <ul> e <li>;
- parole chiave in <strong>.
Non utilizzare <h1>.

IMPORTANTE - AGGIUNTA DELLA GUIDA A SCOMPARSA (COLLAPSIBLE / ACCORDION):
Alla fine della descrizione `body_html`, devi SEMPRE includere un blocco HTML nativo a scomparsa (fisarmonica) strutturato esattamente così:
<details style="margin: 20px 0; border: 1px solid #e5e5e5; border-radius: 8px; padding: 15px; background: #fafafa;">
  <summary style="font-weight: bold; cursor: pointer; color: #2c3e50; font-size: 1.05rem;">☕ Guida alla preparazione e estrazione ottimale</summary>
  <div style="margin-top: 12px; font-size: 0.95rem; color: #444;">
    <p>Istruzioni dettagliate per esaltare al massimo le note aromatiche di questo caffè...</p>
    <ul style="padding-left: 20px; margin-top: 8px;">
      <li><strong>Passo 1:</strong> ...</li>
      <li><strong>Passo 2:</strong> ...</li>
    </ul>
  </div>
</details>

REGOLE SEO:
- seo_title: massimo 60 caratteri, ottimizzato per caffè specialty;
- seo_description: tra 140 e 155 caratteri, descrittiva e orientata alla conversione.

REGOLE TASSATIVE PER L'OUTPUT JSON:
Devi restituire ESCLUSIVAMENTE un oggetto JSON valido contenente queste precise chiavi di primo livello:
1. "seo_title" (stringa)
2. "seo_description" (stringa)
3. "body_html" (stringa HTML comprensiva del blocco <details> finale)
4. "faq_schema" (array di oggetti JSON strutturati con `@type: "Question"`, `name` e `acceptedAnswer`)
5. "howto_schema" (oggetto JSON strutturato come Schema.org HowTo, contenente `name`, `description` e un array `step` dove ogni passo ha `@type: "HowToStep"`, `name` e `text`).
"""

        user_prompt = f"""
Analizza e crea i contenuti ottimizzati per il seguente caffè specialty di Caffè Sansone.

Nome prodotto:
{title}

Descrizione attuale:
{body or "Nessuna descrizione disponibile"}

Varianti del prodotto:
{json.dumps(var_list, ensure_ascii=False)}
"""

        try:
            response = self.ai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3,
                response_format={"type": "json_object"}
            )
            raw_content = response.choices[0].message.content.strip()
            data = json.loads(raw_content)
            
            if not data.get("faq_schema") or not isinstance(data.get("faq_schema"), list):
                data["faq_schema"] = [{
                    "@type": "Question",
                    "name": f"Come conservare al meglio il caffè {title}?",
                    "acceptedAnswer": {
                        "@type": "Answer",
                        "text": "Consigliamo di conservare i chicchi in un luogo fresco e asciutto, lontano da fonti di calore e luce, preferibilmente nella confezione originale dotata di valvola di freschezza."
                    }
                }]

            if not data.get("howto_schema") or not isinstance(data.get("howto_schema"), dict):
                data["howto_schema"] = {
                    "@context": "https://schema.org",
                    "@type": "HowTo",
                    "name": f"Guida alla preparazione di {title}",
                    "description": f"Istruzioni passo-passo per esaltare le note aromatiche di {title}.",
                    "step": [
                        {
                            "@type": "HowToStep",
                            "name": "Macinatura",
                            "text": "Macina i chicchi subito prima dell'estrazione in base al metodo di infusione scelto."
                        }
                    ]
                }

            return data
        except Exception as e:
            print(f"Errore durante la generazione dei contenuti con l'IA: {e}")
            return None

    def prepare_blog_post(self, topic: str):
        """Genera la bozza di un articolo blog tramite OpenAI senza pubblicarla subito."""
        system_prompt = """Sei un copywriter esperto di caffè specialty e torrefazione artigianale per Caffè Sansone.
Scrivi un articolo per il blog coinvolgente, approfondito, autorevole e ottimizzato in ottica SEO per gli amanti del caffè di alta qualità.

REGOLE TASSATIVE PER L'OUTPUT JSON:
Restituisci ESCLUSIVAMENTE un oggetto JSON con queste chiavi:
1. "title" (stringa, titolo accattivante dell'articolo)
2. "summary" (stringa, breve estratto di 2-3 righe)
3. "body_html" (stringa HTML strutturata con tag <p>, <h2>, <ul>, <li>, <strong>)
4. "tags" (stringa di tag separati da virgola, es. "caffè specialty, moka, ricette")
"""
        user_prompt = f"Scrivi un articolo di blog approfondito sul seguente argomento: {topic}"

        try:
            response = self.ai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.4,
                response_format={"type": "json_object"}
            )
            return json.loads(response.choices[0].message.content.strip())
        except Exception as e:
            raise Exception(f"Errore IA generazione bozza blog: {e}")

    def publish_blog_post(self, blog_data: dict):
        """Pubblica ufficialmente l'articolo sul blog di Shopify."""
        graphql_url = f"{self.shop_url}/admin/api/2024-07/graphql.json"
        
        blogs_query = """
        {
          blogs(first: 1) {
            edges {
              node {
                id
              }
            }
          }
        }
        """
        resp = requests.post(graphql_url, json={"query": blogs_query}, headers=self.headers)
        if resp.status_code != 200:
            raise Exception("Impossibile recuperare i blog da Shopify.")
        
        blogs_edges = resp.json().get("data", {}).get("blogs", {}).get("edges", [])
        if not blogs_edges:
            raise Exception("Nessun blog trovato su Shopify. Crea almeno un blog nel pannello di Shopify Admin.")
        
        blog_id = blogs_edges[0]["node"]["id"]

        article_mutation = """
        mutation articleCreate($article: ArticleCreateInput!,$blogId: ID!) {
          articleCreate(article: $article, blogId:$blogId) {
            article {
              id
              title
              handle
            }
            userErrors {
              field
              message
            }
          }
        }
        """
        
        tags_array = [t.strip() for t in blog_data.get("tags", "").split(",") if t.strip()]

        article_variables = {
            "blogId": blog_id,
            "article": {
                "title": blog_data.get("title"),
                "bodyHtml": blog_data.get("body_html"),
                "summary": blog_data.get("summary"),
                "tags": tags_array,
                "isPublished": True
            }
        }

        art_resp = requests.post(graphql_url, json={"query": article_mutation, "variables": article_variables}, headers=self.headers)
        art_json = art_resp.json()
        
        user_errors = art_json.get("data", {}).get("articleCreate", {}).get("userErrors", [])
        if user_errors:
            raise Exception(f"Errore Shopify creazione articolo: {user_errors}")
            
        return art_json.get("data", {}).get("articleCreate", {}).get("article", {})

    def update_product_image_alt_texts(self, product_id, product_title):
        graphql_url = f"{self.shop_url}/admin/api/2024-07/graphql.json"
        query_images = f"""
        {{
          product(id: "gid://shopify/Product/{product_id}") {{
            images(first: 10) {{
              edges {{
                node {{
                  id
                  url
                }}
              }}
            }}
          }}
        }}
        """
        resp = requests.post(graphql_url, json={"query": query_images}, headers=self.headers)
        if resp.status_code != 200:
            return False
            
        edges = resp.json().get("data", {}).get("product", {}).get("images", {}).get("edges", [])
        if not edges:
            return True

        mutation_alt = """
        mutation productUpdateMedia($media: [CreateMediaInput!]!,$productId: ID!) {
          productUpdateMedia(media: $media, productId:$productId) {
            media {
              id
              alt
            }
            userErrors {
              field
              message
            }
          }
        }
        """
        media_inputs = []
        for i, edge in enumerate(edges):
            img_id = edge.get("node", {}).get("id")
            alt_text = f"{product_title} - Caffè Specialty Sansone Vista {i+1}"
            media_inputs.append({
                "id": img_id,
                "alt": alt_text,
                "mediaContentType": "IMAGE"
            })

        variables = {
            "productId": f"gid://shopify/Product/{product_id}",
            "media": media_inputs
        }
        requests.post(graphql_url, json={"query": mutation_alt, "variables": variables}, headers=self.headers)
        return True

    def update_product_seo_and_description(self, product_id, seo_data, tag_to_add="HowTo Ottimizzato"):
        graphql_url = f"{self.shop_url}/admin/api/2024-07/graphql.json"
        
        get_query = f"""
        {{
          product(id: "gid://shopify/Product/{product_id}") {{
            title
            tags
          }}
        }}
        """
        resp = requests.post(graphql_url, json={"query": get_query}, headers=self.headers)
        tags_list = []
        product_title = "Caffè Specialty"
        if resp.status_code == 200:
            node = resp.json().get("data", {}).get("product", {})
            if node:
                product_title = node.get("title", product_title)
                if node.get("tags"):
                    tags_list = node.get("tags")
        
        if tag_to_add not in tags_list:
            tags_list.append(tag_to_add)

        mutation = """
        mutation productUpdate($input: ProductInput!) {
          productUpdate(input: $input) {
            product {
              id
              title
            }
            userErrors {
              field
              message
            }
          }
        }
        """
        
        variables = {
            "input": {
                "id": f"gid://shopify/Product/{product_id}",
                "descriptionHtml": seo_data.get("body_html"),
                "tags": tags_list,
                "seo": {
                    "title": seo_data.get("seo_title"),
                    "description": seo_data.get("seo_description")
                }
            }
        }
        
        response = requests.post(graphql_url, json={"query": mutation, "variables": variables}, headers=self.headers)
        
        if response.status_code == 200:
            result_data = response.json()
            user_errors = result_data.get("data", {}).get("productUpdate", {}).get("userErrors", [])
            if user_errors:
                return False
            
            metafields_to_set = []
            howto_obj = seo_data.get("howto_schema")
            if howto_obj:
                metafields_to_set.append({
                    "ownerId": f"gid://shopify/Product/{product_id}",
                    "namespace": "custom",
                    "key": "how_to_schema",
                    "type": "json",
                    "value": json.dumps(howto_obj, ensure_ascii=False)
                })

            if metafields_to_set:
                metafield_mutation = """
                mutation metafieldsSet($metafields: [MetafieldsSetInput!]!) {
                  metafieldsSet(metafields: $metafields) {
                    metafields {
                      id
                      namespace
                      key
                      value
                    }
                    userErrors {
                      field
                      message
                      code
                    }
                  }
                }
                """
                metafield_variables = {"metafields": metafields_to_set}
                meta_resp = requests.post(graphql_url, json={"query": metafield_mutation, "variables": metafield_variables}, headers=self.headers)
                meta_json = meta_resp.json()
                
                if "errors" in meta_json:
                    return False

                meta_errors = meta_json.get("data", {}).get("metafieldsSet", {}).get("userErrors", [])
                if meta_errors:
                    return False

            self.update_product_image_alt_texts(product_id, product_title)
            return True
        else:
            return False

shop_url = os.getenv("SHOP_URL", "https://348aca-2.myshopify.com")
openai_api_key = os.getenv("OPENAI_API_KEY", "")
client_id = os.getenv("SHOPIFY_CLIENT_ID", "")
client_secret = os.getenv("SHOPIFY_CLIENT_SECRET", "")

agent = ShopifyCoffeeAgent(
    shop_url=shop_url,
    openai_api_key=openai_api_key,
    client_id=client_id,
    client_secret=client_secret
)

@app.get("/", response_class=HTMLResponse)
def read_root():
    return """
    <html>
        <head>
            <title>Caffè Sansone - AI Control Center</title>
            <style>
                body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f4f6f8; color: #333; margin: 0; padding: 30px; }
                .container { max-width: 900px; margin: auto; background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.05); }
                h2 { color: #2c3e50; margin-top: 0; border-bottom: 2px solid #eaeaea; padding-bottom: 15px; }
                .card { background: #fafbfc; padding: 20px; border-radius: 8px; margin-bottom: 25px; border: 1px solid #e1e4e8; }
                .card h3 { margin-top: 0; color: #24292e; }
                label { display: block; margin-bottom: 8px; font-weight: 600; font-size: 14px; }
                input[type="text"] { width: 100%; padding: 10px; margin-bottom: 15px; border: 1px solid #d1d5db; border-radius: 6px; font-size: 14px; box-sizing: border-box; }
                button { padding: 12px 20px; border: none; border-radius: 6px; cursor: pointer; font-size: 14px; font-weight: 600; transition: background 0.2s; }
                .btn-primary { background: #2c3e50; color: white; }
                .btn-primary:hover { background: #1a252f; }
                .btn-success { background: #10b981; color: white; }
                .btn-success:hover { background: #059669; }
            </style>
        </head>
        <body>
            <div class="container">
                <h2>☕ Caffè Sansone - Dashboard Control Center</h2>
                <p>Gestisci l'ottimizzazione dei prodotti e la creazione di articoli con revisione preventiva prima della pubblicazione.</p>
                
                <div class="card">
                    <h3>1. Ottimizzazione Prodotti (Primi 3 in coda)</h3>
                    <p style="font-size: 13px; color: #666; margin-bottom: 15px;">Genera la bozza con descrizione ottimizzata, box a scomparsa e Schema HowTo da revisionare prima di salvarla su Shopify.</p>
                    <form action="/prepare-products" method="get">
                        <button type="submit" class="btn-primary">🔍 Genera e Revisiona Primi 3 Prodotti</button>
                    </form>
                </div>

                <div class="card">
                    <h3>2. Generatore Articoli Blog</h3>
                    <p style="font-size: 13px; color: #666; margin-bottom: 15px;">Crea una bozza di articolo per il blog con l'IA e approvala prima di renderla pubblica online.</p>
                    <form action="/prepare-blog" method="post">
                        <label>Argomento o Titolo dell'articolo:</label>
                        <input type="text" name="topic" placeholder="es. Come abbinare i dolci natalizi al caffè specialty" required />
                        <button type="submit" class="btn-success">✍️ Genera Bozza Articolo</button>
                    </form>
                </div>
            </div>
        </body>
    </html>
    """

@app.get("/prepare-products", response_class=HTMLResponse)
def prepare_products():
    try:
        products = agent.get_products(limit=50)
        pending_products = [p for p in products if "HowTo Ottimizzato" not in p.get("tags", [])]
        target_products = pending_products[:3]
        
        if not target_products:
            return """
            <html><body style="font-family: Arial; padding: 40px; text-align: center;">
                <h3>Nessun prodotto trovato da ottimizzare!</h3>
                <p>Tutti i prodotti hanno già il tag 'HowTo Ottimizzato'.</p>
                <a href="/" style="color: #2c3e50; font-weight: bold;">← Torna alla Dashboard</a>
            </body></html>
            """
            
        previews = []
        for prod in target_products:
            p_id = prod.get("id")
            optimized_data = agent.optimize_coffee_content(prod)
            if optimized_data:
                draft_id = f"prod_{p_id}"
                PENDING_APPROVALS[draft_id] = {
                    "type": "product",
                    "product_id": p_id,
                    "data": optimized_data
                }
                previews.append({
                    "draft_id": draft_id,
                    "title": prod.get("title"),
                    "seo_title": optimized_data.get("seo_title"),
                    "seo_description": optimized_data.get("seo_description"),
                    "body_html": optimized_data.get("body_html")
                })
        
        cards_html = ""
        for p in previews:
            cards_html += f"""
            <div style="background: #fff; border: 1px solid #e1e4e8; border-radius: 8px; padding: 20px; margin-bottom: 25px; box-shadow: 0 2px 5px rgba(0,0,0,0.02);">
                <h3 style="color: #2c3e50; margin-top: 0;">{p['title']}</h3>
                <p><strong>Titolo SEO:</strong> {p['seo_title']}</p>
                <p><strong>Meta Description:</strong> {p['seo_description']}</p>
                <div style="background: #f9f9f9; padding: 15px; border-radius: 6px; border: 1px solid #eee; max-height: 200px; overflow-y: auto; margin: 15px 0; font-size: 13px;">
                    {p['body_html']}
                </div>
                <form action="/approve" method="post" style="display:inline;">
                    <input type="hidden" name="draft_id" value="{p['draft_id']}">
                    <button type="submit" style="background: #10b981; color: white; padding: 10px 18px; border: none; border-radius: 5px; cursor: pointer; font-weight: bold;">✅ Approva e Salva su Shopify</button>
                </form>
            </div>
            """

        return f"""
        <html>
            <head><title>Revisione Prodotti - Caffè Sansone</title></head>
            <body style="font-family: Arial; background: #f4f6f8; padding: 30px;">
                <div style="max-width: 900px; margin: auto;">
                    <h2>📋 Revisione Bozze Prodotti ({len(previews)} trovati)</h2>
                    <p>Controlla le modifiche generate dall'IA. Clicca su approva per applicarle definitivamente sul tuo negozio.</p>
                    <div style="margin: 20px 0;"><a href="/" style="text-decoration: none; color: #2c3e50; font-weight: bold;">← Torna alla Dashboard</a></div>
                    {cards_html}
                </div>
            </body>
        </html>
        """
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})

@app.post("/prepare-blog", response_class=HTMLResponse)
def prepare_blog(topic: str = Form(...)):
    try:
        blog_data = agent.prepare_blog_post(topic)
        draft_id = f"blog_{abs(hash(topic))}"
        PENDING_APPROVALS[draft_id] = {
            "type": "blog",
            "data": blog_data
        }

        return f"""
        <html>
            <head><title>Revisione Articolo Blog - Caffè Sansone</title></head>
            <body style="font-family: Arial; background: #f4f6f8; padding: 30px;">
                <div style="max-width: 900px; margin: auto; background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.05);">
                    <h2>✍️ Revisione Bozza Articolo Blog</h2>
                    <p>Controlla l'articolo generato dall'IA prima di pubblicarlo ufficialmente sul blog di Shopify.</p>
                    <hr style="border:0; border-top: 1px solid #eaeaea; margin: 20px 0;">
                    
                    <h3 style="color: #2c3e50;">{blog_data.get('title')}</h3>
                    <p><strong>Estratto (Summary):</strong> {blog_data.get('summary')}</p>
                    <p><strong>Tag consigliati:</strong> {blog_data.get('tags')}</p>
                    
                    <div style="background: #f9f9f9; padding: 20px; border-radius: 6px; border: 1px solid #eee; margin: 20px 0; max-height: 350px; overflow-y: auto;">
                        {blog_data.get('body_html')}
                    </div>
                    
                    <form action="/approve" method="post" style="display:inline;">
                        <input type="hidden" name="draft_id" value="{draft_id}">
                        <button type="submit" style="background: #10b981; color: white; padding: 12px 20px; border: none; border-radius: 6px; cursor: pointer; font-weight: bold; font-size: 15px;">🚀 Approva e Pubblica sul Blog</button>
                    </form>
                    <a href="/" style="margin-left: 15px; text-decoration: none; color: #666; font-weight: bold;">Annulla</a>
                </div>
            </body>
        </html>
        """
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})

@app.post("/approve", response_class=HTMLResponse)
def approve_draft(draft_id: str = Form(...)):
    if draft_id not in PENDING_APPROVALS:
        return """
        <html><body style="font-family: Arial; padding: 40px; text-align: center;">
            <h3>Bozza non trovata o già approvata/scaduta.</h3>
            <a href="/" style="color: #2c3e50; font-weight: bold;">← Torna alla Dashboard</a>
        </body></html>
        """
    
    item = PENDING_APPROVALS.pop(draft_id)
    item_type = item.get("type")

    try:
        if item_type == "product":
            p_id = item.get("product_id")
            seo_data = item.get("data")
            success = agent.update_product_seo_and_description(p_id, seo_data, tag_to_add="HowTo Ottimizzato")
            if not success:
                raise Exception("Errore durante il salvataggio su Shopify.")
            msg = "Prodotto ottimizzato, aggiornato con box collassabile e pubblicato con successo su Shopify!"
        elif item_type == "blog":
            blog_data = item.get("data")
            article = agent.publish_blog_post(blog_data)
            msg = f"Articolo '{article.get('title')}' pubblicato con successo sul blog di Shopify!"
        else:
            raise Exception("Tipo di elemento non valido.")

        return f"""
        <html>
            <head><title>Operazione Completata</title></head>
            <body style="font-family: Arial; background: #f4f6f8; padding: 50px; text-align: center;">
                <div style="max-width: 600px; margin: auto; background: white; padding: 40px; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.05);">
                    <h2 style="color: #10b981;">✨ Operazione Riuscita!</h2>
                    <p style="font-size: 16px; color: #333; margin: 20px 0;">{msg}</p>
                    <a href="/" style="display: inline-block; margin-top: 20px; background: #2c3e50; color: white; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: bold;">Torna alla Dashboard</a>
                </div>
            </body>
        </html>
        """
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})
