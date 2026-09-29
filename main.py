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

    def get_products(self, limit=50):
        graphql_url = self.shop_url + "/admin/api/2024-07/graphql.json"
        query = """
        {
          products(first: 50) {
            edges {
              node {
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
            raise Exception("Errore di comunicazione con l'API GraphQL di Shopify: " + response.text)

    def append_howto_to_product(self, product_data):
        title = product_data.get("title")
        current_body = product_data.get("body_html", "") or ""
        var_list = product_data.get("variants", [])

        if "Guida alla preparazione e estrazione ottimale" in current_body:
            return {
                "body_html": current_body,
                "howto_schema": {
                    "@context": "https://schema.org",
                    "@type": "HowTo",
                    "name": "Guida alla preparazione di " + str(title),
                    "description": "Istruzioni passo-passo per esaltare le note aromatiche di " + str(title) + ".",
                    "step": [
                        {
                            "@type": "HowToStep",
                            "name": "Dosaggio e Macinatura",
                            "text": "Utilizzare il dosaggio ideale e una macinatura adeguata al metodo di estrazione scelto."
                        },
                        {
                            "@type": "HowToStep",
                            "name": "Estrazione e Temperatura",
                            "text": "Prestare attenzione alla temperatura dell'acqua e ai tempi di infusione per esaltare le caratteristiche aromatiche."
                        }
                    ]
                }
            }

        system_prompt = """Sei un maestro torrefattore ed esperto di caffè specialty per Caffè Sansone.
Il tuo compito è analizzare il nome e la descrizione attuale del prodotto e aggiungere in coda un blocco HTML nativo a scomparsa (fisarmonica) con istruzioni di preparazione REALI, dettagliate e specifiche per questo caffè, senza usare segnaposto o puntini di sospensione.

REGOLA ASSOLUTA SULLA SEO E SUL TESTO ESISTENTE:
- Non modificare, riscrivere o cancellare in alcun modo il testo o i tag HTML già presenti nella descrizione attuale del prodotto.
- Aggiungi in coda solo ed esclusivamente il blocco <details> strutturato esattamente con questo formato HTML (riempiendolo con testi reali e professionali):

<details style="margin: 20px 0; border: 1px solid #e5e5e5; border-radius: 8px; padding: 15px; background: #fafafa;">
  <summary style="font-weight: bold; cursor: pointer; color: #2c3e50; font-size: 1.05rem;">☕ Guida alla preparazione e estrazione ottimale</summary>
  <div style="margin-top: 12px; font-size: 0.95rem; color: #444;">
    <p>Per esaltare al massimo le note aromatiche e il profilo di tostatura artigianale di questo caffè, consigliamo di seguire questi passaggi:</p>
    <ul style="padding-left: 20px; margin-top: 8px;">
      <li><strong>Dosaggio e Macinatura:</strong> [Scrivi qui indicazioni precise sul rapporto caffè/acqua e sulla grana della macinatura]</li>
      <li><strong>Temperatura dell'acqua:</strong> [Indica la temperatura ideale, es. 90-94°C]</li>
      <li><strong>Estrazione:</strong> [Fornisci dettagli sul tempo di estrazione o sul metodo consigliato come V65, espresso o moka]</li>
    </ul>
  </div>
</details>

REGOLE TASSATIVE PER L'OUTPUT JSON:
Devi restituire ESCLUSIVAMENTE un oggetto JSON valido con queste chiavi:
1. "body_html" (stringa HTML: l'intera descrizione originale + il blocco <details> compilato con contenuti reali, senza mai inserire '...' o segnaposti).
2. "howto_schema" (oggetto JSON strutturato come Schema.org HowTo, con name, description e un array "step" contenente almeno 3 oggetti con @type: "HowToStep", name e text reali).
"""

        user_prompt = "Nome prodotto: " + str(title) + "\n\nDescrizione attuale da preservare integralmente:\n" + str(current_body) + "\n\nVarianti:\n" + json.dumps(var_list, ensure_ascii=False)

        try:
            response = self.ai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.2,
                response_format={"type": "json_object"}
            )
            data = json.loads(response.choices[0].message.content.strip())
            
            if not data.get("body_html"):
                data["body_html"] = current_body
                
            return data
        except Exception as e:
            print("Errore generazione HowTo: " + str(e))
            return None

    def get_creative_blog_ideas(self):
        system_prompt = """Sei il consulente di marketing e content strategy per Caffè Sansone, micro-torrefazione artigianale di Napoli.
Genera 4 spunti originali, di nicchia e di grande interesse tecnico-culturale per un articolo di blog sul caffè specialty. Evita assolutamente qualsiasi allucinazione o invenzione commerciale priva di fondamento: basati su dati tecnici reali (estrazione, chimica dell'acqua, profili di tostatura, storia della torrefazione artigianale).

RESTUISCI ESCLUSIVAMENTE UN OGGETTO JSON con una chiave "ideas" che contiene un array di 4 oggetti, ciascuno con:
- "title" (titolo professionale e accattivante dell'articolo proposto)
- "angle" (breve spiegazione del rigore tecnico e del valore storico per i clienti)
"""
        try:
            response = self.ai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": "Proponi 4 spunti seri, tecnici e rigorosi per il blog."}
                ],
                temperature=0.3,
                response_format={"type": "json_object"}
            )
            content = response.choices[0].message.content
            if not content:
                raise Exception("Risposta vuota da OpenAI")
            parsed = json.loads(content.strip())
            return parsed.get("ideas", [])
        except Exception as e:
            print("Errore recupero spunti blog: " + str(e))
            return [
                {"title": "L'importanza della mineralizzazione dell'acqua nell'estrazione del V60", "angle": "Focus tecnico sulla chimica in tazza."},
                {"title": "Dal chicco alla tazzina: viaggio nei metodi di lavorazione lavati e naturali", "angle": "Approfondimento agronomico e di torrefazione."}
            ]

    def prepare_blog_post(self, topic: str):
        system_prompt = """Sei un copywriter ed esperto di caffè specialty per Caffè Sansone. 
Scrivi un articolo per il blog rigoroso, professionale, privo di qualsiasi allucinazione o invenzione di fantasia, basato unicamente su fonti certe e sul rispetto della tradizione artigianale della torrefazione.

REGOLE TASSATIVE PER L'OUTPUT JSON:
Restituisci ESCLUSIVAMENTE un oggetto JSON con queste chiavi:
1. "title" (stringa, titolo autorevole dell'articolo)
2. "summary" (stringa, breve estratto sintetico e professionale)
3. "body_html" (stringa HTML strutturata con tag <p>, <h2>, <ul>, <li>, <strong>)
4. "tags" (stringa di tag separati da virgola, es. "caffè specialty, tostatura, estrazione")
"""
        user_prompt = "Scrivi un articolo di blog approfondito e rigoroso sul seguente argomento: " + str(topic)

        try:
            response = self.ai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.2,
                response_format={"type": "json_object"}
            )
            content = response.choices[0].message.content
            if not content:
                raise Exception("Risposta vuota da OpenAI per il post del blog.")
            
            data = json.loads(content.strip())
            if not data or not isinstance(data, dict):
                raise Exception("Formato JSON non valido restituito dall'IA.")
            return data
        except Exception as e:
            raise Exception("Errore IA generazione bozza blog: " + str(e))

    def publish_blog_post(self, blog_data: dict):
        graphql_url = self.shop_url + "/admin/api/2024-07/graphql.json"
        
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
            raise Exception("Nessun blog trovato su Shopify.")
        
        blog_id = blogs_edges[0]["node"]["id"]

        article_mutation = """
        mutation articleCreate($article: ArticleCreateInput!, $blogId: ID!) {
          articleCreate(article: $article, blogId: $blogId) {
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
            raise Exception("Errore Shopify creazione articolo: " + str(user_errors))
            
        return art_json.get("data", {}).get("articleCreate", {}).get("article", {})

    def update_product_image_alt_texts(self, product_id, product_title):
        graphql_url = self.shop_url + "/admin/api/2024-07/graphql.json"
        query_images = "{\n  product(id: \"gid://shopify/Product/" + str(product_id) + "\") {\n    images(first: 10) {\n      edges {\n        node {\n          id\n          url\n        }\n      }\n    }\n  }\n}"
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
            alt_text = str(product_title) + " - Caffè Specialty Sansone Vista " + str(i + 1)
            media_inputs.append({
                "id": img_id,
                "alt": alt_text,
                "mediaContentType": "IMAGE"
            })

        variables = {
            "productId": "gid://shopify/Product/" + str(product_id),
            "media": media_inputs
        }
        requests.post(graphql_url, json={"query": mutation_alt, "variables": variables}, headers=self.headers)
        return True

    def update_product_description_and_howto(self, product_id, update_data, tag_to_add="HowTo Ottimizzato"):
        graphql_url = self.shop_url + "/admin/api/2024-07/graphql.json"
        
        get_query = "{\n  product(id: \"gid://shopify/Product/" + str(product_id) + "\") {\n    title\n    tags\n  }\n}"
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
                "id": "gid://shopify/Product/" + str(product_id),
                "descriptionHtml": update_data.get("body_html"),
                "tags": tags_list
            }
        }
        
        response = requests.post(graphql_url, json={"query": mutation, "variables": variables}, headers=self.headers)
        
        if response.status_code == 200:
            result_data = response.json()
            user_errors = result_data.get("data", {}).get("productUpdate", {}).get("userErrors", [])
            if user_errors:
                return False
            
            metafields_to_set = []
            howto_obj = update_data.get("howto_schema")
            if howto_obj:
                metafields_to_set.append({
                    "ownerId": "gid://shopify/Product/" + str(product_id),
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
    ideas = agent.get_creative_blog_ideas()
    ideas_html = ""
    for idea in ideas:
        t = idea.get("title", "")
        a = idea.get("angle", "")
        ideas_html += (
            '<div style="background: white; border: 1px solid #e1e4e8; padding: 12px; border-radius: 6px; margin-bottom: 10px; display: flex; justify-content: space-between; align-items: center;">'
            '<div><strong>' + str(t) + '</strong><br><span style="font-size: 12px; color: #666;">' + str(a) + '</span></div>'
            '<form action="/prepare-blog" method="post" style="margin: 0;">'
            '<input type="hidden" name="topic" value="' + str(t) + '">'
            '<button type="submit" style="background: #27ae60; color: white; border: none; padding: 8px 12px; border-radius: 4px; cursor: pointer; font-size: 12px; font-weight: bold;">Usa questo spunto</button>'
            '</form></div>'
        )

    return (
        "<html>"
        "<head>"
        "<title>Caffè Sansone - AI Control Center</title>"
        "<style>"
        "body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f4f6f8; color: #333; margin: 0; padding: 30px; }"
        ".container { max-width: 900px; margin: auto; background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.05); }"
        "h2 { color: #2c3e50; margin-top: 0; border-bottom: 2px solid #eaeaea; padding-bottom: 15px; }"
        ".card { background: #fafbfc; padding: 20px; border-radius: 8px; margin-bottom: 25px; border: 1px solid #e1e4e8; }"
        ".card h3 { margin-top: 0; color: #24292e; }"
        "label { display: block; margin-bottom: 8px; font-weight: 600; font-size: 14px; }"
        "input[type='text'] { width: 100%; padding: 10px; margin-bottom: 15px; border: 1px solid #d1d5db; border-radius: 6px; font-size: 14px; box-sizing: border-box; }"
        "button { padding: 12px 20px; border: none; border-radius: 6px; cursor: pointer; font-size: 14px; font-weight: 600; transition: background 0.2s; }"
        ".btn-primary { background: #2c3e50; color: white; }"
        ".btn-primary:hover { background: #1a252f; }"
        "</style>"
        "</head>"
        "<body>"
        "<div class=\"container\">"
        "<h2>☕ Caffè Sansone - Dashboard Control Center</h2>"
        "<p>Gestione rigorosa e professionale: zero allucinazioni, rispetto totale della storia del brand e della SEO esistente.</p>"
        "<div class=\"card\">"
        "<h3>1. Integrazione HowTo Prodotti (Primi 3 in coda)</h3>"
        "<p style=\"font-size: 13px; color: #666; margin-bottom: 15px;\">Aggiunge il box a scomparsa con istruzioni dettagliate in fondo alla descrizione esistente e aggiorna il JSON Schema HowTo.</p>"
        "<form action=\"/prepare-products\" method=\"get\">"
        "<button type=\"submit\" class=\"btn-primary\">🔍 Aggiungi HowTo ai Primi 3 Prodotti (Revisione)</button>"
        "</form>"
        "</div>"
        "<div class=\"card\">"
        "<h3>2. Generatore Articoli Blog & Spunti Strategici</h3>"
        "<p style=\"font-size: 13px; color: #666; margin-bottom: 15px;\">Spunti professionali verificati creati dall'IA per il tuo blog. Clicca su uno spunto per generare la bozza completa o inserisci un argomento:</p>"
        + ideas_html +
        "<form action=\"/prepare-blog\" method=\"post\" style=\"margin-top: 15px;\">"
        "<label>Oppure scrivi un argomento personalizzato:</label>"
        "<input type=\"text\" name=\"topic\" placeholder=\"es. Metodi di estrazione specialty e profilo aromatico\" required />"
        "<button type=\"submit\" class=\"btn-primary\" style=\"background: #27ae60;\">✍️ Genera Bozza Blog Professionale</button>"
        "</form>"
        "</div>"
        "</div>"
        "</body>"
        "</html>"
    )

@app.get("/prepare-products", response_class=HTMLResponse)
def prepare_products():
    try:
        products = agent.get_products(limit=50)
        pending_products = [p for p in products if "HowTo Ottimizzato" not in p.get("tags", [])]
        target_products = pending_products[:3]
        
        if not target_products:
            return (
                "<html><body style=\"font-family: Arial; padding: 40px; text-align: center;\">"
                "<h3>Nessun prodotto trovato da aggiornare!</h3>"
                "<p>Tutti i prodotti hanno già il tag 'HowTo Ottimizzato'.</p>"
                "<a href=\"/\" style=\"color: #2c3e50; font-weight: bold;\">← Torna alla Dashboard</a>"
                "</body></html>"
            )
            
        previews = []
        for prod in target_products:
            p_id = prod.get("id")
            update_data = agent.append_howto_to_product(prod)
            if update_data:
                draft_id = "prod_" + str(p_id)
                PENDING_APPROVALS[draft_id] = {
                    "type": "product",
                    "product_id": p_id,
                    "data": update_data
                }
                previews.append({
                    "draft_id": draft_id,
                    "title": prod.get("title"),
                    "body_html": update_data.get("body_html")
                })
        
        cards_html = ""
        for p in previews:
            cards_html += (
                '<div style="background: #fff; border: 1px solid #e1e4e8; border-radius: 8px; padding: 20px; margin-bottom: 25px; box-shadow: 0 2px 5px rgba(0,0,0,0.02);">'
                '<h3 style="color: #2c3e50; margin-top: 0;">' + str(p["title"]) + '</h3>'
                '<p style="font-size: 13px; color: #10b981; font-weight: bold;">ℹ️ La SEO attuale e i testi originali sono intatti. Verrà inserito il box HowTo dettagliato in fondo.</p>'
                '<div style="background: #f9f9f9; padding: 15px; border-radius: 6px; border: 1px solid #eee; max-height: 250px; overflow-y: auto; margin: 15px 0; font-size: 13px;">' + str(p["body_html"]) + '</div>'
                '<form action="/approve" method="post" style="display:inline;">'
                '<input type="hidden" name="draft_id" value="' + str(p["draft_id"]) + '">'
                '<button type="submit" style="background: #10b981; color: white; padding: 10px 18px; border: none; border-radius: 5px; cursor: pointer; font-weight: bold;">✅ Approva e Aggiorna su Shopify</button>'
                '</form></div>'
            )

        return (
            "<html>"
            "<head><title>Revisione HowTo Prodotti - Caffè Sansone</title></head>"
            "<body style=\"font-family: Arial; background: #f4f6f8; padding: 30px;\">"
            "<div style=\"max-width: 900px; margin: auto;\">"
            "<h2>📋 Revisione Inserimento HowTo (" + str(len(previews)) + " prodotti)</h2>"
            "<p>Controlla che il box a scomparsa contenga tutti i passi dettagliati corretti prima dell'invio a Shopify.</p>"
            "<div style=\"margin: 20px 0;\"><a href=\"/\" style=\"text-decoration: none; color: #2c3e50; font-weight: bold;\">← Torna alla Dashboard</a></div>"
            + cards_html +
            "</div>"
            "</body>"
            "</html>"
        )
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})

@app.get("/prepare-blog", response_class=RedirectResponse)
def prepare_blog_get():
    # Gestisce i tentativi di accesso via GET (es. bot di Google o navigazione diretta) reindirizzando alla home
    return RedirectResponse(url="/", status_code=303)

@app.post("/prepare-blog", response_class=HTMLResponse)
def prepare_blog(topic: str = Form(...)):
    try:
        blog_data = agent.prepare_blog_post(topic)
        if not blog_data:
            raise Exception("Impossibile generare la bozza dell'articolo.")
            
        draft_id = "blog_" + str(abs(hash(topic)))
        PENDING_APPROVALS[draft_id] = {
            "type": "blog",
            "data": blog_data
        }

        return (
            "<html>"
            "<head><title>Revisione Articolo Blog - Caffè Sansone</title></head>"
            "<body style=\"font-family: Arial; background: #f4f6f8; padding: 30px;\">"
            "<div style=\"max-width: 900px; margin: auto; background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.05);\">"
            "<h2>✍️ Revisione Bozza Articolo Blog Professionale</h2>"
            "<p>Controlla l'articolo verificato generato dall'IA prima di pubblicarlo sul blog di Shopify.</p>"
            "<hr style=\"border:0; border-top: 1px solid #eaeaea; margin: 20px 0;\">"
            "<h3 style=\"color: #2c3e50;\">" + str(blog_data.get('title', '')) + "</h3>"
            "<p><strong>Estratto (Summary):</strong> " + str(blog_data.get('summary', '')) + "</p>"
            "<p><strong>Tag consigliati:</strong> " + str(blog_data.get('tags', '')) + "</p>"
            "<div style=\"background: #f9f9f9; padding: 20px; border-radius: 6px; border: 1px solid #eee; margin: 20px 0; max-height: 350px; overflow-y: auto;\">"
            + str(blog_data.get('body_html', '')) +
            "</div>"
            "<form action=\"/approve\" method=\"post\" style=\"display:inline;\">"
            "<input type=\"hidden\" name=\"draft_id\" value=\"" + str(draft_id) + "\">"
            "<button type=\"submit\" style=\"background: #10b981; color: white; padding: 12px 20px; border: none; border-radius: 6px; cursor: pointer; font-weight: bold; font-size: 15px;\">🚀 Approva e Pubblica sul Blog</button>"
            "</form>"
            "<a href=\"/\" style=\"margin-left: 15px; text-decoration: none; color: #666; font-weight: bold;\">Annulla</a>"
            "</div>"
            "</body>"
            "</html>"
        )
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})

@app.post("/approve", response_class=HTMLResponse)
def approve_draft(draft_id: str = Form(...)):
    if draft_id not in PENDING_APPROVALS:
        return (
            "<html><body style=\"font-family: Arial; padding: 40px; text-align: center;\">"
            "<h3>Bozza non trovata o già approvata/scaduta.</h3>"
            "<a href=\"/\" style=\"color: #2c3e50; font-weight: bold;\">← Torna alla Dashboard</a>"
            "</body></html>"
        )
    
    item = PENDING_APPROVALS.pop(draft_id)
    item_type = item.get("type")

    try:
        if item_type == "product":
            p_id = item.get("product_id")
            update_data = item.get("data")
            success = agent.update_product_description_and_howto(p_id, update_data, tag_to_add="HowTo Ottimizzato")
            if not success:
                raise Exception("Errore durante il salvataggio su Shopify.")
            msg = "Blocco HowTo dettagliato aggiunto in coda alla descrizione e JSON Schema aggiornato con successo! (La SEO precedente e i testi originali sono intatti)."
        elif item_type == "blog":
            blog_data = item.get("data")
            article = agent.publish_blog_post(blog_data)
            msg = "Articolo professionale '" + str(article.get('title')) + "' pubblicato con successo sul blog di Shopify!"
        else:
            raise Exception("Tipo di elemento non valido.")

        return (
            "<html>"
            "<head><title>Operazione Completata</title></head>"
            "<body style=\"font-family: Arial; background: #f4f6f8; padding: 50px; text-align: center;\">"
            "<div style=\"max-width: 600px; margin: auto; background: white; padding: 40px; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.05);\">"
            "<h2 style=\"color: #10b981;\">✨ Operazione Riuscita!</h2>"
            "<p style=\"font-size: 16px; color: #333; margin: 20px 0;\">" + str(msg) + "</p>"
            "<a href=\"/\" style=\"display: inline-block; margin-top: 20px; background: #2c3e50; color: white; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: bold;\">Torna alla Dashboard</a>"
            "</div>"
            "</body>"
            "</html>"
        )
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})
