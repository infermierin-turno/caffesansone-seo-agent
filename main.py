def update_product_seo_and_description(self, product_id, seo_data, tag_to_add="HowTo Ottimizzato"):
        graphql_url = f"{self.shop_url}/admin/api/2024-07/graphql.json"
        
        # 1. Recupera tag esistenti
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

        # 2. Aggiorna Prodotto (Descrizione, SEO, Tag)
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
            
            # 3. Imposta i Metafield (FAQ e HowTo)
            metafields_to_set = []
            
            faq_obj = seo_data.get("faq_schema")
            if faq_obj:
                metafields_to_set.append({
                    "ownerId": f"gid://shopify/Product/{product_id}",
                    "namespace": "custom",
                    "key": "faq_schema",
                    "type": "json",
                    "value": json.dumps(faq_obj, ensure_ascii=False)
                })

            howto_obj = seo_data.get("howto_schema")
            if howto_obj:
                metafields_to_set.append({
                    "ownerId": f"gid://shopify/Product/{product_id}",
                    "namespace": "custom",
                    "key": "howto_schema",
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
                    # Non blocchiamo interamente se falliscono i metafields, ma lo logghiamo

            return True
        else:
            print(f"[ERRORE HTTP PRODOTTO]: {response.text}")
            return False
