import os
import json
import random
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

    def append_howto_to_product(self, product_data, user_directive=""):
        title = product_data.get("title")
        current_body = product_data.get("body_html", "") or ""
        var_list = product_data.get("variants", [])

        system_prompt = f"""Sei un maestro torrefattore ed esperto di caffè specialty per Caffè Sansone.
Il tuo compito è analizzare il nome e la descrizione attuale del prodotto e aggiungere in coda un blocco HTML nativo a scomparsa (fisarmonica) con istruzioni di preparazione REALI, dettagliate e specifiche per questo caffè, senza usare segnaposto o puntini di sospensione.

DIRETTIVA AGGIUNTIVA FORNITA DAL DIRETTORE (DA SEGUIRE RIGOROSAMENTE):
{user_directive if user_directive else "Nessuna direttiva specifica, procedi con standard artigianali eccellenti."}

REGOLA ASSOLUTA SULLA SEO E SUL TESTO ESISTENTE:
- Non modificare, riscrivere o cancellare in alcun modo il testo o i tag HTML già presenti nella descrizione attuale del prodotto.
- Aggiungi in coda solo ed esclusivamente il blocco <details> strutturato esattamente con questo formato HTML:

<details style="margin: 20px 0; border: 1px solid #e5e5e5; border-radius: 8px; padding: 15px; background: #fafafa;">
  <summary style="font-weight: bold; cursor: pointer; color: #2c3e50; font-size: 1.05rem;">☕ Guida alla preparazione e estrazione ottimale</summary>
  <div style="margin-top: 12px; font-size: 0.95rem; color: #444;">
    <p>Per esaltare al massimo le note aromatiche e il profilo di tostatura artigianale di questo caffè, consigliamo di seguire questi passaggi:</p>
    <ul style="padding-left: 20px; margin-top: 8px;">
      <li><strong>Dosaggio e Macinatura:</strong> [Indicazioni precise]</li>
      <li><strong>Temperatura dell'acqua:</strong> [Temperatura ideale]</li>
      <li><strong>Estrazione:</strong> [Dettagli sul tempo o metodo]</li>
    </ul>
  </div>
</details>

REGOLE TASSATIVE PER L'OUTPUT JSON:
Restituisci ESCLUSIVAMENTE un oggetto JSON con:
1. "body_html" (stringa HTML: descrizione originale + blocco <details> compilato).
2. "howto_schema" (oggetto JSON strutturato come Schema.org HowTo dinamico).
"""

        user_prompt = "Nome prodotto: " + str(title) + "\n\nDescrizione attuale:\n" + str(current_body) + "\n\nVarianti:\n" + json.dumps(var_list, ensure_ascii=False)

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
                
            if "howto_schema" in data and isinstance(data["howto_schema"], dict):
                data["howto_schema"]["name"] = "Preparazione del Caffè " + str(title)
                data["howto_schema"]["description"] = "Guida dettagliata per preparare un caffè perfetto utilizzando " + str(title) + "."

            return data
        except Exception as e:
            print("Errore generazione HowTo: " + str(e))
            return None

    def suggest_merchandising_for_product(self, product_id, user_directive=""):
        target_prod = self.get_product_by_id(product_id)
        if not target_prod:
            raise Exception("Prodotto caffè non trovato.")
            
        all_prods = self.get_all_products(limit=50)
        
        merch_candidates = []
        for p in all_prods:
            if str(p["id"]) != str(target_prod["id"]):
                merch_candidates.append({
                    "id": p["id"],
                    "title": p["title"],
                    "handle": p["handle"],
                    "type": p["product_type"]
                })

        system_prompt = f"""Sei il direttore commerciale di Caffè Sansone. 
Il tuo compito è selezionare dal catalogo Shopify disponibile i 2 o 3 prodotti di merchandising o accessori che meglio si abbinano a questo specifico caffè per l'inserimento nei metafield di prodotti complementari.

DIRETTIVA AGGIUNTIVA FORNITA DAL DIRETTORE (DA SEGUIRE RIGOROSAMENTE):
{user_directive if user_directive else "Nessuna direttiva specifica, scegli i prodotti con criterio commerciale ottimale."}

REGOLE TASSATIVE PER L'OUTPUT JSON:
Restituisci ESCLUSIVAMENTE un oggetto JSON con:
1. "selected_ids" (array di stringhe contenente unicamente gli ID numerici dei 2 o 3 prodotti di merchandising scelti)
2. "merchandising_summary" (stringa con un breve commento strategico).
"""

        user_prompt = "Caffè di riferimento:\n" + json.dumps(target_prod, ensure_ascii=False) + "\n\nCatalogo Merchandising disponibile:\n" + json.dumps(merch_candidates, ensure_ascii=False)

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
            data = json.loads(response.choices[0].message.content.strip())
            
            selected_ids = data.get("selected_ids", [])
            chosen_details = []
            for p in merch_candidates:
                if str(p["id"]) in [str(x) for x in selected_ids]:
                    chosen_details.append(p)

            return {
                "product_id": target_prod["id"],
                "title": target_prod["title"],
                "selected_ids": [str(x) for x in selected_ids],
                "chosen_details": chosen_details,
                "summary": data.get("merchandising_summary", "")
            }
        except Exception as e:
            raise Exception("Errore IA suggerimento merchandising: " + str(e))

    def update_product_merchandising_metafields(self, product_id, merch_ids):
        graphql_url = self.shop_url + "/admin/api/2024-07/graphql.json"
        owner_gid = "gid://shopify/Product/" + str(product_id)
        
        # Formattazione corretta dei GID dei prodotti complementari come array JSON stringificato
        product_gids = ["gid://shopify/Product/" + str(m_id).split("/")[-1] for m_id in merch_ids]
        
        metafields_to_set = [
            {
                "ownerId": owner_gid,
                "namespace": "custom",
                "key": "complementary_products",
                "type": "list.product_reference",
                "value": json.dumps(product_gids)
            }
        ]

        mutation = """
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
        variables = {"metafields": metafields_to_set}
        response = requests.post(graphql_url, json={"query": mutation, "variables": variables}, headers=self.headers)
        
        if response.status_code == 200:
            result_json = response.json()
            print("Risposta Shopify MetafieldsSet:", json.dumps(result_json))
            user_errors = result_json.get("data", {}).get("metafieldsSet", {}).get("userErrors", [])
            if user_errors:
                print("Errori metafieldsSet:", user_errors)
                raise Exception(f"Errore Shopify Metafield: {user_errors[0].get('message')} (Campo: {user_errors[0].get('field')})")
            return True
        else:
            raise Exception(f"Errore HTTP Shopify: {response.status_code} - {response.text}")

    def get_creative_blog_ideas(self):
        focus_topics = [
            "la chimica dell'acqua e dei minerali nell'estrazione del caffè",
            "le differenze sensoriali tra i processi di lavorazione (naturali, lavati, honey)",
            "il profilo di tostatura medio-chiaro per metodi filtro vs espresso napoletano",
            "storia e evoluzione della cultura del caffè a Napoli tra tradizione e innovazione",
            "come conservare i chicchi di caffè specialty a casa per preservare i terpeni aromatici"
        ]
        chosen_focus = random.sample(focus_topics, min(3, len(focus_topics)))

        system_prompt = (
            "Sei il consulente di marketing e content strategy per Caffè Sansone, micro-torrefazione artigianale di Napoli.\n"
            "Il tuo compito è generare 4 spunti originali, di nicchia e di grande interesse tecnico-culturale per un articolo di blog.\n"
            "Fattore di diversificazione richiesto: concentra la creatività su questi ambiti: " + ", ".join(chosen_focus) + ".\n\n"
            "RESTUISCI ESCLUSIVAMENTE UN OGGETTO JSON con una chiave \"ideas\" che contiene un array di 4 oggetti con \"title\" e \"angle\"."
        )
        try:
            response = self.ai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": "Genera 4 spunti unici."}
                ],
                temperature=0.7,
                response_format={"type": "json_object"}
            )
            content = response.choices[0].message.content
            if not content:
                raise Exception("Risposta vuota da OpenAI")
            return json.loads(content.strip()).get("ideas", [])
        except Exception as e:
            print("Errore spunti blog: " + str(e))
            return [{"title": "L'importanza dell'acqua nell'estrazione", "angle": "Focus chimico."}]

    def prepare_blog_post(self, topic: str, user_directive=""):
        system_prompt = f"""Sei un copywriter ed esperto di caffè specialty per Caffè Sansone. 
Scrivi un articolo per il blog rigoroso, professionale e basato sulla tradizione artigianale.

DIRETTIVA AGGIUNTIVA FORNITA DAL DIRETTORE (DA SEGUIRE RIGOROSAMENTE):
{user_directive if user_directive else "Nessuna direttiva specifica."}

REGOLE TASSATIVE PER L'OUTPUT JSON:
Restituisci ESCLUSIVAMENTE un oggetto JSON con:
1. "title" (stringa)
2. "summary" (stringa)
3. "body_html" (stringa HTML strutturata con <p>, <h2>, <ul>, <li>, <strong>)
4. "tags" (stringa di tag separati da virgola)
"""
        user_prompt = "Argomento dell'articolo: " + str(topic)

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
            content = response.choices[0].message.content
            if not content:
                raise Exception("Risposta vuota da OpenAI.")
            return json.loads(content.strip())
        except Exception as e:
            raise Exception("Errore generazione blog: " + str(e))

    def publish_blog_post(self, blog_data: dict):
        graphql_url = self.shop_url + "/admin/api/2024-07/graphql.json"
        blogs_query = "{\n  blogs(first: 1) {\n    edges {\n      node {\n        id\n      }\n    }\n  }\n}"
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
        "input[type='text'], textarea { width: 100%; padding: 10px; margin-bottom: 15px; border: 1px solid #d1d5db; border-radius: 6px; font-size: 14px; box-sizing: border-box; }"
        "button { padding: 12px 20px; border: none; border-radius: 6px; cursor: pointer; font-size: 14px; font-weight: 600; transition: background 0.2s; }"
        ".btn-primary { background: #2c3e50; color: white; }"
        ".btn-primary:hover { background: #1a252f; }"
        "</style>"
        "</head>"
        "<body>"
        "<div class=\"container\">"
        "<h2>☕ Caffè Sansone - Dashboard Control Center</h2>"
        "<p>Gestione rigorosa e professionale: zero allucinazioni, rispetto totale della storia del brand e della SEO esistente.</p>"
        
        # Sezione 1: HowTo
        "<div class=\"card\">"
        "<h3>1. Ricerca e Inserimento HowTo per ID Prodotto</h3>"
        "<form action=\"/prepare-product-by-id\" method=\"get\">"
        "<label>ID Prodotto Caffè (Shopify):</label>"
        "<input type=\"text\" name=\"product_id\" placeholder=\"Inserisci l'ID del prodotto...\" required />"
        "<label>La tua indicazione / direttiva personalizzata (opzionale):</label>"
        "<textarea name=\"user_directive\" rows=\"2\" placeholder=\"Es. Enfatizza la moka napoletana e la macinatura fine...\"></textarea>"
        "<button type=\"submit\" class=\"btn-primary\">🔍 Cerca e Genera HowTo (Revisione)</button>"
        "</form>"
        "</div>"

        # Sezione 2: Merchandising
        "<div class=\"card\">"
        "<h3>2. Suggerisci Merchandising in Metafield (Prodotti Complementari)</h3>"
        "<form action=\"/prepare-merchandising-by-id\" method=\"get\">"
        "<label>ID Prodotto Caffè (Shopify):</label>"
        "<input type=\"text\" name=\"product_id\" placeholder=\"Inserisci l'ID del prodotto caffè...\" required />"
        "<label>La tua indicazione / direttiva personalizzata (opzionale):</label>"
        "<textarea name=\"user_directive\" rows=\"2\" placeholder=\"Es. Abbina preferibilmente tazze in ceramica o teli...\"></textarea>"
        "<button type=\"submit\" class=\"btn-primary\" style=\"background: #e67e22;\">🎁 Suggerisci Merchandising (Metafield)</button>"
        "</form>"
        "</div>"

        # Sezione 3: Blog
        "<div class=\"card\">"
        "<h3>3. Generatore Articoli Blog & Spunti Strategici</h3>"
        "<p style=\"font-size: 13px; color: #666; margin-bottom: 15px;\">Spunti creati dall'IA. Ricarica la pagina per vederne di nuovi:</p>"
        + ideas_html +
        "<form action=\"/prepare-blog\" method=\"post\" style=\"margin-top: 15px;\">"
        "<label>Oppure scrivi un argomento personalizzato:</label>"
        "<input type=\"text\" name=\"topic\" placeholder=\"es. Metodi di estrazione specialty\" required />"
        "<label>La tua indicazione / direttiva personalizzata (opzionale):</label>"
        "<textarea name=\"user_directive\" rows=\"2\" placeholder=\"Es. Mantieni un tono molto tecnico e incentrato sull'estrazione a freddo...\"></textarea>"
        "<button type=\"submit\" class=\"btn-primary\" style=\"background: #27ae60;\">✍️ Genera Bozza Blog Professionale</button>"
        "</form>"
        "</div>"
        "</div>"
        "</body>"
        "</html>"
    )

@app.get("/prepare-product-by-id", response_class=HTMLResponse)
def prepare_product_by_id(product_id: str, user_directive: str = ""):
    try:
        prod = agent.get_product_by_id(product_id)
        if not prod:
            return "<html><body style='font-family: Arial; padding: 40px; text-align: center;'><h3>Prodotto non trovato!</h3><a href='/'>← Torna alla Dashboard</a></body></html>"
            
        update_data = agent.append_howto_to_product(prod, user_directive=user_directive)
        if not update_data:
            raise Exception("Impossibile generare i dati HowTo.")
            
        draft_id = "prod_" + str(prod.get("id"))
        PENDING_APPROVALS[draft_id] = {
            "type": "product",
            "product_id": prod.get("id"),
            "data": update_data
        }
        
        card_html = (
            '<div style="background: #fff; border: 1px solid #e1e4e8; border-radius: 8px; padding: 20px; margin-bottom: 25px;">'
            '<h3 style="color: #2c3e50; margin-top: 0;">' + str(prod.get("title")) + ' (ID: ' + str(prod.get("id")) + ')</h3>'
            f'<p style="font-size: 13px; color: #2980b9; font-weight: bold;">💬 Tua direttiva applicata: {user_directive if user_directive else "Nessuna"}</p>'
            '<div style="background: #f9f9f9; padding: 15px; border-radius: 6px; border: 1px solid #eee; max-height: 250px; overflow-y: auto; margin: 15px 0; font-size: 13px;">' + str(update_data.get("body_html")) + '</div>'
            '<form action="/approve" method="post" style="display:inline;">'
            '<input type="hidden" name="draft_id" value="' + str(draft_id) + '">'
            '<button type="submit" style="background: #10b981; color: white; padding: 10px 18px; border: none; border-radius: 5px; cursor: pointer; font-weight: bold;">✅ Approva e Aggiorna su Shopify</button>'
            '</form></div>'
        )

        return (
            "<html><head><title>Revisione HowTo</title></head>"
            "<body style=\"font-family: Arial; background: #f4f6f8; padding: 30px;\">"
            "<div style=\"max-width: 900px; margin: auto;\">"
            "<h2>📋 Revisione Inserimento HowTo</h2><a href=\"/\">← Torna alla Dashboard</a>"
            + card_html + "</div></body></html>"
        )
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})

@app.get("/prepare-merchandising-by-id", response_class=HTMLResponse)
def prepare_merchandising_by_id(product_id: str, user_directive: str = ""):
    try:
        res = agent.suggest_merchandising_for_product(product_id, user_directive=user_directive)
        draft_id = "merch_" + str(res.get("product_id"))
        PENDING_APPROVALS[draft_id] = {
            "type": "merchandising",
            "product_id": res.get("product_id"),
            "selected_ids": res.get("selected_ids")
        }

        chosen_items_html = ""
        for item in res.get("chosen_details", []):
            chosen_items_html += '<li style="margin-bottom: 6px;"><strong>' + str(item.get("title")) + '</strong> <span style="color: #666; font-size: 12px;">(ID: ' + str(item.get("id")) + ')</span></li>'

        card_html = (
            '<div style="background: #fff; border: 1px solid #e1e4e8; border-radius: 8px; padding: 20px; margin-bottom: 25px;">'
            '<h3 style="color: #2c3e50; margin-top: 0;">' + str(res.get("title")) + ' (ID: ' + str(res.get("product_id")) + ')</h3>'
            f'<p style="font-size: 13px; color: #2980b9; font-weight: bold;">💬 Tua direttiva applicata: {user_directive if user_directive else "Nessuna"}</p>'
            '<p style="font-size: 13px; color: #e67e22; font-weight: bold;">💡 Analisi IA per i Metafield: ' + str(res.get("summary")) + '</p>'
            '<ul style="padding-left: 20px; font-size: 13px; color: #444;">' + chosen_items_html + '</ul>'
            '<form action="/approve" method="post" style="margin-top: 20px; display:inline;">'
            '<input type="hidden" name="draft_id" value="' + str(draft_id) + '">'
            '<button type="submit" style="background: #e67e22; color: white; padding: 10px 18px; border: none; border-radius: 5px; cursor: pointer; font-weight: bold;">✅ Salva nei Metafield su Shopify</button>'
            '</form></div>'
        )

        return (
            "<html><head><title>Revisione Merchandising</title></head>"
            "<body style=\"font-family: Arial; background: #f4f6f8; padding: 30px;\">"
            "<div style=\"max-width: 900px; margin: auto;\">"
            "<h2>🎁 Revisione Collegamento Metafield</h2><a href=\"/\">← Torna alla Dashboard</a>"
            + card_html + "</div></body></html>"
        )
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})

@app.post("/prepare-blog", response_class=HTMLResponse)
def prepare_blog(topic: str = Form(...), user_directive: str = Form("")):
    try:
        blog_data = agent.prepare_blog_post(topic, user_directive=user_directive)
        if not blog_data:
            raise Exception("Impossibile generare la bozza dell'articolo.")
            
        draft_id = "blog_" + str(abs(hash(topic)))
        PENDING_APPROVALS[draft_id] = {
            "type": "blog",
            "data": blog_data
        }

        return (
            "<html><head><title>Revisione Articolo Blog</title></head>"
            "<body style=\"font-family: Arial; background: #f4f6f8; padding: 30px;\">"
            "<div style=\"max-width: 900px; margin: auto; background: white; padding: 30px; border-radius: 12px;\">"
            "<h2>✍️ Revisione Bozza Articolo Blog Professionale</h2>"
            f"<p style='color: #2980b9; font-weight: bold;'>💬 Tua direttiva applicata: {user_directive if user_directive else 'Nessuna'}</p>"
            "<hr style=\"border:0; border-top: 1px solid #eaeaea; margin: 20px 0;\">"
            "<h3 style=\"color: #2c3e50;\">" + str(blog_data.get('title', '')) + "</h3>"
            "<p><strong>Estratto:</strong> " + str(blog_data.get('summary', '')) + "</p>"
            "<div style=\"background: #f9f9f9; padding: 20px; border-radius: 6px; border: 1px solid #eee; margin: 20px 0; max-height: 350px; overflow-y: auto;\">"
            + str(blog_data.get('body_html', '')) +
            "</div>"
            "<form action=\"/approve\" method=\"post\" style=\"display:inline;\">"
            "<input type=\"hidden\" name=\"draft_id\" value=\"" + str(draft_id) + "\">"
            "<button type=\"submit\" style=\"background: #10b981; color: white; padding: 12px 20px; border: none; border-radius: 6px; cursor: pointer; font-weight: bold;\">🚀 Approva e Pubblica</button>"
            "</form>"
            "<a href=\"/\" style=\"margin-left: 15px; text-decoration: none; color: #666; font-weight: bold;\">Annulla</a>"
            "</div></body></html>"
        )
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})

@app.post("/approve", response_class=HTMLResponse)
def approve_draft(draft_id: str = Form(...)):
    if draft_id not in PENDING_APPROVALS:
        return "<html><body style='font-family: Arial; padding: 40px; text-align: center;'><h3>Bozza non trovata o scaduta.</h3><a href='/'>← Torna alla Dashboard</a></body></html>"
    
    item = PENDING_APPROVALS.pop(draft_id)
    item_type = item.get("type")

    try:
        if item_type == "product":
            success = agent.update_product_description_and_howto(item.get("product_id"), item.get("data"))
            if not success: raise Exception("Errore salvataggio su Shopify.")
            msg = "Blocco HowTo aggiunto con successo!"
        elif item_type == "merchandising":
            success = agent.update_product_merchandising_metafields(item.get("product_id"), item.get("selected_ids"))
            if not success: raise Exception("Errore salvataggio metafield.")
            msg = "Prodotti di merchandising collegati con successo nei metafield!"
        elif item_type == "blog":
            pub_res = agent.publish_blog_post(item.get("data"))
            msg = "Articolo pubblicato con successo!"
        else:
            raise Exception("Tipo non riconosciuto.")

        return (
            "<html><body style=\"font-family: Arial; padding: 40px; text-align: center; background: #f4f6f8;\">"
            "<div style=\"max-width: 600px; margin: auto; background: white; padding: 30px; border-radius: 12px;\">"
            "<h2 style=\"color: #10b981;\">Operazione completata con successo!</h2>"
            "<p>" + msg + "</p>"
            "<div style=\"margin-top: 25px;\"><a href=\"/\" style=\"background: #2c3e50; color: white; padding: 10px 20px; border-radius: 6px; text-decoration: none; font-weight: bold;\">← Torna alla Dashboard</a></div>"
            "</div></body></html>"
        )
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})
