import os
import json
import requests
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from openai import OpenAI
from shopify_agent import ShopifyCoffeeAgent

app = FastAPI(title="Caffè Sansone - HowTo SEO Agent")

shop_url = os.getenv("SHOP_URL") or "https://caffesansone.it"
openai_api_key = os.getenv("OPENAI_API_KEY")
client_id = os.getenv("SHOPIFY_CLIENT_ID")
client_secret = os.getenv("SHOPIFY_CLIENT_SECRET")

client_openai = OpenAI(api_key=openai_api_key)

agent = ShopifyCoffeeAgent(
    shop_url=shop_url,
    openai_api_key=openai_api_key,
    client_id=client_id,
    client_secret=client_secret
)

def generate_howto_json(product_title: str, product_description: str) -> str:
    prompt = f"""
Sei un esperto di caffè specialty, micro-torrefazione artigianale, estrazioni avanzate e contenuti SEO per caffesansone.it.

Devi generare una guida pratica HowTo in italiano, valida per il caffè specialty indicato sotto.

DATI DEL PRODOTTO
Titolo:
<product_title>
{product_title}
</product_title>

Descrizione:
<product_description>
{product_description}
</product_description>

OBIETTIVO
Crea una guida pratica, professionale e utile per:
- macinare correttamente i grani in base all'estrazione;
- preparare l'acqua e impostare la temperatura ideale;
- eseguire l'estrazione (espresso, filtro o cold brew);
- conservare il caffè torrefatto artigianalmente.
"""

    json_schema = {
        "name": "howto_guide",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["title", "description", "steps"],
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Il titolo principale della guida HowTo di preparazione."
                },
                "description": {
                    "type": "string",
                    "description": "Una breve descrizione introduttiva personalizzata per il caffè."
                },
                "steps": {
                    "type": "array",
                    "minItems": 4,
                    "maxItems": 4,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["name", "text"],
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Il titolo del passaggio."
                            },
                            "text": {
                                "type": "string",
                                "description": "Il testo descrittivo del passaggio."
                            }
                        }
                    }
                }
            }
        }
    }

    try:
        response = client_openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_schema", "json_schema": json_schema},
            temperature=0.2
        )
        content = response.choices[0].message.content.strip()
        parsed_data = json.loads(content)
        if "steps" not in parsed_data or len(parsed_data["steps"]) != 4:
            raise ValueError("Il numero di passaggi generati non è esattamente 4.")
        return content
    except Exception as e:
        print(f"Errore nella generazione dello schema HowTo per '{product_title}': {e}")
        fallback_data = {
            "title": f"Guida alla preparazione ottimale di {product_title}",
            "description": "Istruzioni di base per esaltare il profilo aromatico in tazza.",
            "steps": [
                {"name": "1. Scelta della macinatura", "text": "Macina i grani freschi subito prima dell'estrazione."},
                {"name": "2. Controllo dell'acqua", "text": "Utilizza acqua a basso residuo fisso tra 90°C e 94°C."},
                {"name": "3. Estrazione e dosaggio", "text": "Pesa accuratamente la dose di caffè e rispetta i tempi."},
                {"name": "4. Conservazione", "text": "Richiudi bene la confezione con la valvola salvafreschezza."}
            ]
        }
        return json.dumps(fallback_data, ensure_ascii=False)

@app.get("/", response_class=HTMLResponse)
def read_root():
    return """
    <!DOCTYPE html>
    <html lang="it">
    <head>
        <meta charset="UTF-8">
        <title>Caffè Sansone - HowTo Agent</title>
        <script src="https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4"></script>
    </head>
    <body class="bg-amber-50/30 text-gray-900 font-sans antialiased">
        <div class="max-w-2xl mx-auto p-12">
            <h1 class="text-3xl font-bold text-amber-800 mb-4">Caffè Sansone - HowTo SEO</h1>
            <p class="text-gray-600 mb-6">Inserisci l'ID del prodotto Shopify per generare e applicare la guida di estrazione HowTo nei metafield:</p>
            <form action="/apply-howto" method="get" class="flex gap-3">
                <input type="text" name="product_id" placeholder="ID Prodotto Shopify" required
                    class="flex-1 px-4 py-2 border rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-amber-500">
                <button type="submit" class="bg-amber-700 hover:bg-amber-800 text-white font-medium px-5 py-2 rounded-lg text-sm transition shadow">
                    Genera & Salva HowTo
                </button>
            </form>
        </div>
    </body>
    </html>
    """

@app.get("/apply-howto", response_class=HTMLResponse)
def apply_howto_product(product_id: str):
    clean_input = product_id.strip()
    if not clean_input.startswith("gid://"):
        numeric_id = clean_input.split("/")[-1]
        raw_gid = f"gid://shopify/Product/{numeric_id}"
    else:
        raw_gid = clean_input

    graphql_url = f"{agent.shop_url}/admin/api/2024-07/graphql.json"

    # Recupera dati del prodotto tramite GraphQL
    product_query = """
    query getProduct($id: ID!) {
      product(id: $id) {
        id
        title
        descriptionHtml
      }
    }
    """
    prod_resp = requests.post(
        graphql_url,
        json={"query": product_query, "variables": {"id": raw_gid}},
        headers=agent.headers
    )

    if prod_resp.status_code != 200:
        raise HTTPException(status_code=500, detail=f"Errore di comunicazione con l'API GraphQL di Shopify: {prod_resp.text}")

    prod_resp_json = prod_resp.json()
    if "errors" in prod_resp_json:
        raise HTTPException(status_code=400, detail=f"Errore GraphQL Shopify: {prod_resp_json['errors']}")

    prod_data = prod_resp_json.get("data", {}).get("product")
    if not prod_data:
        raise HTTPException(status_code=404, detail=f"Prodotto non trovato su Shopify per il GID: {raw_gid}")

    title = prod_data.get("title", "Caffè Specialty")
    body_html = prod_data.get("descriptionHtml", "") or ""

    # Genera il HowTo tramite IA
    howto_json_str = generate_howto_json(title, body_html)

    # Salva nel metafield custom.howto_schema tramite GraphQL
    metafield_mutation = """
    mutation metafieldsSet($metafields: [MetafieldsSetInput!]!) {
      metafieldsSet(metafields: $metafields) {
        metafields {
          id
          namespace
          key
        }
        userErrors {
          field
          message
        }
      }
    }
    """
    
    variables = {
        "metafields": [{
            "ownerId": raw_gid,
            "namespace": "custom",
            "key": "howto_schema",
            "type": "json",
            "value": howto_json_str
        }]
    }

    meta_resp = requests.post(graphql_url, json={"query": metafield_mutation, "variables": variables}, headers=agent.headers)
    if meta_resp.status_code != 200:
        raise HTTPException(status_code=500, detail="Errore di comunicazione con l'API GraphQL per il salvataggio.")
    
    meta_data = meta_resp.json()
    errors = meta_data.get("data", {}).get("metafieldsSet", {}).get("userErrors", [])
    if errors:
        raise HTTPException(status_code=500, detail=f"Errore Shopify Metafield: {errors}")

    return f"""
    <!DOCTYPE html>
    <html lang="it">
    <head><script src="https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4"></script></head>
    <body class="bg-amber-50/30 p-12">
        <div class="max-w-xl mx-auto bg-white p-8 rounded-xl shadow border border-amber-200 text-center">
            <h1 class="text-xl font-bold text-amber-800 mb-2">Guida HowTo Salvata!</h1>
            <p class="text-gray-600 mb-4">Il metafield <code>custom.howto_schema</code> è stato aggiornato correttamente per il prodotto: <strong>{title}</strong></p>
            <a href="/" class="inline-block bg-amber-700 text-white px-5 py-2 rounded-lg text-sm">Torna alla Home</a>
        </div>
    </body>
    </html>
    """

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
