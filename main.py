import os
import json
import requests
from fastapi import FastAPI, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from openai import OpenAI

app = FastAPI()

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
        """Ottiene il token di accesso tramite OAuth Client Credentials con Shopify."""
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
            print(f"[SHOPIFY AUTH] Tentativo di richiesta token a: {auth_url}")
            response = requests.post(auth_url, json=payload, headers=headers)
            if response.status_code == 200:
                data = response.json()
                token = data.get("access_token")
                if token:
                    return token
            raise Exception(f"Risposta Shopify {response.status_code}: {response.text}")
        except Exception as e:
            print(f"[ERRORE] Impossibile generare l'access token con Client ID e Secret: {e}")
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

REGOLE SEO:
- seo_title: massimo 60 caratteri, ottimizzato per caffè specialty;
- seo_description: tra 140 e 155 caratteri, descrittiva e orientata alla conversione.

REGOLE TASSATIVE PER L'OUTPUT JSON:
Devi restituire ESCLUSIVAMENTE un oggetto JSON valido contenente queste precise chiavi di primo livello:
1. "seo_title" (stringa)
2. "seo_description" (stringa)
3. "body_html" (stringa HTML)
4. "faq_schema" (array di oggetti JSON strutturati con `@type: "Question"`, `name` e `acceptedAnswer`)
5. "howto_schema" (oggetto JSON strutturato come Schema.org HowTo, contenente `name`, `description` e un array `step` dove ogni passo ha `@type: "HowToStep"`, `name` e `text`).

Esempio di struttura richiesta per howto_schema:
{
  "name": "Come preparare al meglio...",
  "description": "Guida passo-passo per un'estrazione perfetta...",
  "step": [
    {
      "@type": "HowToStep",
      "name": "Preparazione dell'acqua",
      "text": "Usa acqua a basso residuo fisso..."
    }
  ]
}"""

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
                        },
                        {
                            "@type": "HowToStep",
                            "name": "Estrazione",
                            "text": "Procedi all'estrazione seguendo i tempi e le proporzioni ideali per valorizzare il profilo aromatico."
                        }
                    ]
                }

            return data
        except Exception as e:
            print(f"Errore durante la generazione dei contenuti con l'IA: {e}")
            return None

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
        print(f"[DEBUG SHOPIFY PRODOTTO] Status: {response.status_code}, Body: {response.text}")
        
        if response.status_code == 200:
            result_data = response.json()
            user_errors = result_data.get("data", {}).get("productUpdate", {}).get("userErrors", [])
            if user_errors:
                print(f"[ERRORE GRAPHQL PRODOTTO USER ERRORS]: {user_errors}")
                return False
            
            metafields_to_set = []
            
            faq_obj = seo_data.get("faq_schema")
            if faq_obj:
                metafields_to_set.append({
                    "ownerId": f"gid://shopify/Product/{product_id}",
                    "namespace": "custom",
                    "key": "faq_prodotto",
                    "type": "json",
                    "value": json.dumps(faq_obj, ensure_ascii=False)
                })

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
                      key
                      field
                      message
                    }
                  }
                }
                """
                metafield_variables = {"metafields": metafields_to_set}
                meta_resp = requests.post(graphql_url, json={"query": metafield_mutation, "variables": metafield_variables}, headers=self.headers)
                print(f"[DEBUG SHOPIFY METAFIELDS] Status: {meta_resp.status_code}, Body: {meta_resp.text}")
                
                meta_json = meta_resp.json()
                meta_errors = meta_json.get("data", {}).get("metafieldsSet", {}).get("userErrors", [])
                if meta_errors:
                    print(f"[ERRORE GRAPHQL METAFIELDS USER ERRORS]: {meta_errors}")

            self.update_product_image_alt_texts(product_id, product_title)
            return True
        else:
            print(f"[ERRORE HTTP PRODOTTO]: {response.text}")
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
        <head><title>Caffè Sansone AI Agent - Specialty Coffee</title></head>
        <body style="font-family: Arial; padding: 40px;">
            <h2>Agent Caffè Sansone Attivo (HowTo & Metafield Manager)</h2>
            <p>Il servizio OAuth è operativo.</p>
            <form action="/test-and-optimize-first3" method="get">
                <button type="submit" style="padding: 12px 24px; background: #2c3e50; color: white; border: none; border-radius: 5px; cursor: pointer; font-size: 16px;">
                    Ottimizza i primi 3 prodotti senza HowTo
                </button>
            </form>
        </body>
    </html>
    """

@app.get("/test-and-optimize-first3")
def test_and_optimize_first3():
    try:
        products = agent.get_products(limit=50)
        pending_products = [p for p in products if "HowTo Ottimizzato" not in p.get("tags", [])]
        target_products = pending_products[:3]
        
        if not target_products:
            return {"status": "success", "message": "Nessun prodotto trovato da ottimizzare: tutti hanno già il tag 'HowTo Ottimizzato'."}
            
        results = []
        for prod in target_products:
            p_id = prod.get("id")
            p_title = prod.get("title")
            
            optimized_data = agent.optimize_coffee_content(prod)
            if not optimized_data:
                results.append({"id": p_id, "title": p_title, "status": "errore generazione IA"})
                continue
                
            success = agent.update_product_seo_and_description(p_id, optimized_data, tag_to_add="HowTo Ottimizzato")
            if success:
                results.append({"id": p_id, "title": p_title, "status": "successo - HowTo e Metafield popolati"})
            else:
                results.append({"id": p_id, "title": p_title, "status": "errore salvataggio Shopify"})
                
        return {
            "status": "completed",
            "processed_count": len(results),
            "details": results
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})

@app.post("/optimize")
def optimize_product(product_id: str = Form(...)):
    try:
        products = agent.get_products(limit=100)
        target_product = None
        for p in products:
            if str(p.get("id")) == str(product_id):
                target_product = p
                break
        
        if not target_product:
            raise HTTPException(status_code=404, detail="Prodotto non trovato su Shopify.")
            
        optimized_data = agent.optimize_coffee_content(target_product)
        if not optimized_data:
            raise HTTPException(status_code=500, detail="Errore durante la generazione dei contenuti con l'IA.")
            
        success = agent.update_product_seo_and_description(product_id, optimized_data, tag_to_add="HowTo Ottimizzato")
        if not success:
            raise HTTPException(status_code=500, detail="Errore durante il salvataggio su Shopify.")
            
        return {"status": "success", "message": f"Prodotto specialty {product_id} ottimizzato con guida HowTo e tag 'HowTo Ottimizzato'!"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})
