import os
import json
import requests
from openai import OpenAI

class ShopifyCoffeeAgent:
    def __init__(self, shop_url, openai_api_key, client_id=None, client_secret=None, access_token=None, **kwargs):
        self.shop_url = shop_url.rstrip('/')
        self.ai_client = OpenAI(api_key=openai_api_key)
        
        # Recupera il token da qualsiasi variabile disponibile
        self.access_token = (
            access_token 
            or os.getenv("SHOPIFY_ACCESS_TOKEN") 
            or os.getenv("SHOPIFY_TOKEN") 
            or client_secret 
            or client_id
        )
        
        # Determina il corretto formato dell'header in base al tipo di token Shopify
        token_str = str(self.access_token).strip() if self.access_token else ""
        
        headers = {
            "Content-Type": "application/json"
        }
        
        if token_str.startswith("shpss_") or token_str.startswith("atkn_"):
            # I token di sessione/app moderni (shpss, atkn) spesso richiedono il Bearer token o funzionano meglio con Authorization
            headers["Authorization"] = f"Bearer {token_str}"
        else:
            # I token classici Admin API (shpat) usano X-Shopify-Access-Token
            headers["X-Shopify-Access-Token"] = token_str

        self.headers = headers

    def get_products(self, limit=50):
        """Recupera l'elenco dei prodotti con relative varianti tramite Shopify GraphQL Admin API."""
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
            if "errors" in data:
                print(f"[ERRORE] Errore restituito dall'API GraphQL di Shopify: {data['errors']}")
                return []
                
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
            print(f"[ERRORE] Comunicazione fallita con Shopify (Status {response.status_code}): {response.text}")
            return []
