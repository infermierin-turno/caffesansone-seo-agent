import os
import json
import requests
from fastapi import FastAPI, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from openai import OpenAI

app = FastAPI()

class ShopifyCoffeeAgent:
    def __init__(self, shop_url, openai_api_key, client_id=None, client_secret=None, access_token=None, **kwargs):
        self.shop_url = shop_url.rstrip('/')
        self.ai_client = OpenAI(api_key=openai_api_key)
        
        self.access_token = (
            access_token 
            or os.getenv("SHOPIFY_ACCESS_TOKEN") 
            or os.getenv("SHOPIFY_ADMIN_ACCESS_TOKEN")
        )
        
        if not self.access_token:
            self.client_id = client_id or os.getenv("SHOPIFY_CLIENT_ID") or os.getenv("SHOPIFY_API_KEY")
            self.client_secret = client_secret or os.getenv("SHOPIFY_CLIENT_SECRET") or os.getenv("SHOPIFY_SECRET") or os.getenv("SHOPIFY_API_SECRET")
            self.access_token = self._get_admin_access_token()
        
        self.headers = {
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": self.access_token if self.access_token else ""
        }

    def _get_admin_access_token(self):
        if not self.client_id or not self.client_secret:
            print("[AVVISO] Client ID o Client Secret mancanti.")
            return None
        return self.client_secret

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
            print(f"[ERRORE] Impossibile recuperare i prodotti via GraphQL: {response.text}")
            return []

    def get_pending_products(self, limit=3):
        all_products = self.get_products(limit=50)
        pending = []
        for p in all_products:
            tags = p.get("tags", [])
            if isinstance(tags, str):
                tags_list = [t.strip() for t in tags.split(",")]
            else:
                tags_list = tags
            
            if "Ottimizzato IA" not in tags_list:
                pending.append(p)
                if len(pending) >= limit:
                    break
        return pending

    def optimize_divise_content(self, product_data_or_title, current_body=None, variants=None):
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

        system_prompt = """Sei un copywriter esperto di abbigliamento professionale e divise per i settori sanitario, estetico, sala, cucina, ristorazione e hospitality.

Scrivi descrizioni per un e-commerce professionale. La voce del brand è competente, concreta, affidabile e rassicurante. Il tono è professionale ma naturale, diretto e comprensibile. Usa frasi brevi, verbi attivi e informazioni utili per aiutare il cliente nella scelta.

Metti in evidenza:
- comfort e libertà di movimento;
- vestibilità;
- tessuti e composizione;
- resistenza ai lavaggi;
- facilità di manutenzione;
- tasche, chiusure, elasticità e dettagli funzionali se presenti nel testo originale;
- utilizzo professionale consigliato;
- possibilità di personalizzazione tranne che per scarpe e pantaloni;
- informazioni utili per favorire la decisione d’acquisto;
- il problema o bisogno risolto dal prodotto;
- contesti professionali adatti.

REGOLA FONDAMENTALE SUI LINK:
Se nella descrizione attuale del prodotto è presente un link (ad esempio un URL o un file PDF della guida alle taglie), DEVI COPIARLO ESATTAMENTE così come si trova, senza modificarlo, senza inventarlo e senza sostituirlo con altri indirizzi. Se non è presente alcun link nel testo originale, non inserire alcun link.

REGOLA FONDAMENTALE GENERALE:
Non inventare mai caratteristiche, materiali, certificazioni, proprietà tecniche, vestibilità, colori, misure o prestazioni non presenti nelle informazioni fornite.

Non descrivere un prodotto come antibatterico, antimacchia, ignifugo, impermeabile, elasticizzato, certificato, traspirante o adatto a uno specifico utilizzo se queste caratteristiche non sono esplicitamente indicate.

Se un'informazione non è disponibile, omettila. Non fare supposizioni e non presentare come certe informazioni generiche normalmente associate a quel tipo di prodotto.

La descrizione HTML deve essere ordinata e legibile e può contenere:
- un'introduzione con <p>;
- titoli <h2> descrittivi;
- elenchi puntati con <ul> e <li>;
- parole importanti in <strong>;
- tag HTML <a> esclusivamente per riportare fedelmente eventuali link già presenti nei dati originali.

Non utilizzare <h1>. Non inserire markdown, emoji, shortcode o codice JavaScript nel corpo HTML.

REGOLE SEO:
- seo_title: massimo 60 caratteri, chiaro e descrittivo;
- seo_description: idealmente tra 140 e 155 caratteri, naturale e utile per il cliente;
- non inserire parole chiave in modo artificiale.

REGOLE TASSATIVE PER L'OUTPUT JSON:
Devi restituire ESCLUSIVAMENTE un oggetto JSON valido contenente queste precise chiavi di primo livello:
1. "seo_title" (stringa)
2. "seo_description" (stringa)
3. "body_html" (stringa HTML)
4. "faq_schema" (array di oggetti JSON, obbligatorio, strutturato esattamente con `@type: "Question"`, `name` e `acceptedAnswer` con `@type: "Answer"` e `text`).

Esempio di struttura richiesta:
{
  "seo_title": "...",
  "seo_description": "...",
  "body_html": "<p>...</p>",
  "faq_schema": [
    {
      "@type": "Question",
      "name": "Domanda...",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "Risposta..."
      }
    }
  ]
}"""

        user_prompt = f"""
Analizza e riscrivi il seguente prodotto per il nostro e-commerce.

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
                fallback_faqs = []
                if var_list:
                    variants_text = ", ".join([v.get("title", "") for v in var_list if v.get("title")])
                    fallback_faqs.append({
                        "@type": "Question",
                        "name": f"Quali varianti sono disponibili per {title}?",
                        "acceptedAnswer": {
                            "@type": "Answer",
                            "text": f"Il prodotto {title} è disponibile nelle seguenti varianti: {variants_text}."
                        }
                    })
                data["faq_schema"] = fallback_faqs

            return data
        except Exception as e:
            print(f"Errore durante la generazione o il parsing JSON dall'IA: {e}")
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
            alt_text = f"{product_title} - Vista {i+1} abbigliamento professionale"
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

    def update_product_seo_and_description(self, product_id, seo_data, tag_to_add="Ottimizzato IA"):
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
        product_title = "Prodotto Professionale"
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
              descriptionHtml
              tags
              seo {
                title
                description
              }
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
                print(f"[ERRORE GRAPHQL PRODOTTO] {user_errors}")
                return False
            
            faq_obj = seo_data.get("faq_schema")
            if faq_obj:
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
                    }
                  }
                }
                """
                metafield_variables = {
                    "metafields": [
                        {
                            "ownerId": f"gid://shopify/Product/{product_id}",
                            "namespace": "custom",
                            "key": "faq_schema",
                            "type": "json",
                            "value": json.dumps(faq_obj, ensure_ascii=False)
                        }
                    ]
                }
                
                requests.post(graphql_url, json={"query": metafield_mutation, "variables": metafield_variables}, headers=self.headers)

            self.update_product_image_alt_texts(product_id, product_title)
            return True
        else:
            return False

shop_url = os.getenv("SHOP_URL", "https://caffesansone.it")
openai_api_key = os.getenv("OPENAI_API_KEY", "")
shopify_token = os.getenv("SHOPIFY_ACCESS_TOKEN", "")

agent = ShopifyCoffeeAgent(
    shop_url=shop_url,
    openai_api_key=openai_api_key,
    access_token=shopify_token
)

@app.get("/", response_class=HTMLResponse)
def read_root():
    return """
    <html>
        <head><title>Caffè Sansone AI Agent</title></head>
        <body style="font-family: Arial; padding: 40px;">
            <h2>Agent Shopify & OpenAI Attivo</h2>
            <p>Il servizio è pronto per elaborare i prodotti.</p>
        </body>
    </html>
    """

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
            
        optimized_data = agent.optimize_divise_content(target_product)
        if not optimized_data:
            raise HTTPException(status_code=500, detail="Errore durante la generazione dei contenuti con l'IA.")
            
        success = agent.update_product_seo_and_description(product_id, optimized_data)
        if not success:
            raise HTTPException(status_code=500, detail="Errore durante il salvataggio su Shopify.")
            
        return {"status": "success", "message": f"Prodotto {product_id} ottimizzato con successo!"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})
