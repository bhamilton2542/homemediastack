from flask import Flask, jsonify, request, Response
import json
import os
import urllib.request
import urllib.parse

app = Flask(__name__)

DATA_FILE = os.path.join(os.path.dirname(__file__), "data", "dinners.json")

DEFAULT_DINNERS = [
    {"name": "Tacos", "link": None},
    {"name": "Spaghetti & Meatballs", "link": None},
    {"name": "Stir Fry", "link": None},
    {"name": "Homemade Pizza", "link": None},
    {"name": "Grilled Chicken & Veggies", "link": None},
    {"name": "Burgers", "link": None},
    {"name": "Curry Night", "link": None},
    {"name": "Breakfast for Dinner", "link": None},
    {"name": "Sheet Pan Fajitas", "link": None},
    {"name": "Soup & Grilled Cheese", "link": None},
]

MEALIE_URL = os.environ.get("MEALIE_URL", "")
MEALIE_API_TOKEN = os.environ.get("MEALIE_API_TOKEN", "")
MEALIE_SHOPPING_LIST_ID = os.environ.get("MEALIE_SHOPPING_LIST_ID", "")


def load_dinners():
    if not os.path.exists(DATA_FILE):
        save_dinners(DEFAULT_DINNERS)
        return DEFAULT_DINNERS
    with open(DATA_FILE, "r") as f:
        dinners = json.load(f)

    if dinners and isinstance(dinners[0], str):
        dinners = [{"name": name, "link": None} for name in dinners]
        save_dinners(dinners)

    return dinners


def save_dinners(dinners):
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w") as f:
        json.dump(dinners, f, indent=2)


def mealie_request(method, path, body=None):
    url = f"{MEALIE_URL}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {MEALIE_API_TOKEN}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = resp.read().decode("utf-8")
        if not raw.strip():
            return {}
        return json.loads(raw)


@app.route("/api/dinners", methods=["GET"])
def get_dinners():
    dinners = load_dinners()
    return jsonify([d["name"] for d in dinners])


@app.route("/api/dinners", methods=["POST"])
def add_dinner():
    body = request.json or {}
    name = body.get("name", "").strip()
    link = (body.get("link") or "").strip() or None
    if not name:
        return jsonify({"error": "Name required"}), 400
    dinners = load_dinners()
    if not any(d["name"] == name for d in dinners):
        dinners.append({"name": name, "link": link})
        save_dinners(dinners)
    return jsonify([d["name"] for d in dinners])


@app.route("/api/dinners/<path:name>", methods=["DELETE"])
def remove_dinner(name):
    dinners = load_dinners()
    dinners = [d for d in dinners if d["name"] != name]
    save_dinners(dinners)
    return jsonify([d["name"] for d in dinners])


@app.route("/api/dinners/<path:name>/link", methods=["GET"])
def get_dinner_link(name):
    dinners = load_dinners()
    match = next((d for d in dinners if d["name"] == name), None)
    if not match:
        return jsonify({"error": "Dinner not found"}), 404
    return jsonify({"name": match["name"], "link": match.get("link")})


@app.route("/api/mealie/recipe/<path:dinner_name>", methods=["GET"])
def get_mealie_recipe(dinner_name):
    if not MEALIE_URL or not MEALIE_API_TOKEN:
        return jsonify({"found": False, "error": "Mealie not configured"}), 200

    try:
        query = urllib.parse.quote(dinner_name)
        results = mealie_request("GET", f"/api/recipes?search={query}")
        items = results.get("items", [])

        if not items:
            return jsonify({"found": False})

        slug = items[0]["slug"]
        recipe = mealie_request("GET", f"/api/recipes/{slug}")

        ingredients = [
            ing["display"] for ing in recipe.get("recipeIngredient", []) if ing.get("display")
        ]

        return jsonify({
            "found": True,
            "recipeName": recipe.get("name"),
            "ingredients": ingredients,
        })
    except Exception as e:
        return jsonify({"found": False, "error": str(e)}), 200


@app.route("/api/mealie/shopping-list", methods=["POST"])
def add_to_mealie_shopping_list():
    """Add the specific, user-approved ingredients to Mealie's shopping list.

    Each ingredient is first run through Mealie's own NLP ingredient parser
    to extract a structured quantity + food reference. Rather than relying
    on Mealie's own automatic consolidation (which, per a known issue,
    doesn't reliably trigger for items created via the API), we handle
    consolidation ourselves: before creating a new item, we check for an
    existing unchecked item on the list with the same food, and if found,
    add to its quantity instead of creating a duplicate line.
    """
    if not MEALIE_URL or not MEALIE_API_TOKEN or not MEALIE_SHOPPING_LIST_ID:
        return jsonify({"error": "Mealie not configured"}), 400

    ingredients = (request.json or {}).get("ingredients", [])
    if not ingredients:
        return jsonify({"error": "No ingredients provided"}), 400

    added = []
    failed = []

    for ingredient_text in ingredients:
        try:
            item_payload = {
                "shoppingListId": MEALIE_SHOPPING_LIST_ID,
                "note": ingredient_text,
                "display": ingredient_text,
            }
            food_id = None
            food_name = None
            unit_name = None
            parsed_quantity = 1

            try:
                parsed = mealie_request("POST", "/api/parser/ingredient", {
                    "ingredient": ingredient_text,
                    "parser": "nlp",
                })
                parsed_ing = parsed.get("ingredient", {})
                food = parsed_ing.get("food")
                quantity = parsed_ing.get("quantity")

                if food and food.get("id"):
                    food_id = food["id"]
                    food_name = food.get("name", "")
                    parsed_quantity = quantity if quantity else 1
                    item_payload["foodId"] = food_id
                    item_payload["quantity"] = parsed_quantity
                    unit = parsed_ing.get("unit")
                    if unit and unit.get("id"):
                        item_payload["unitId"] = unit["id"]
                        unit_name = unit.get("name", "")
            except Exception:
                pass

            existing_match = None
            if food_id:
                current_list = mealie_request(
                    "GET", f"/api/households/shopping/lists/{MEALIE_SHOPPING_LIST_ID}"
                )
                for existing_item in current_list.get("listItems", []):
                    same_food = existing_item.get("foodId") == food_id
                    existing_unit = (existing_item.get("unit") or {}).get("name")
                    same_unit = existing_unit == unit_name
                    if same_food and same_unit and not existing_item.get("checked"):
                        existing_match = existing_item
                        break

            if existing_match:
                new_quantity = (existing_match.get("quantity") or 0) + parsed_quantity
                existing_match["quantity"] = new_quantity
                unit_part = f"{unit_name} " if unit_name else ""
                display_text = f"{new_quantity:g} {unit_part}{food_name}".strip() if food_name else existing_match.get("display", "")
                existing_match["display"] = display_text
                existing_match["note"] = display_text
                mealie_request(
                    "PUT",
                    f"/api/households/shopping/items/{existing_match['id']}",
                    existing_match,
                )
            else:
                mealie_request("POST", "/api/households/shopping/items", item_payload)

            added.append(ingredient_text)
        except Exception as e:
            failed.append({"item": ingredient_text, "error": str(e)})

    return jsonify({"added": added, "failed": failed})


@app.route("/shopping-list/toggle/<item_id>", methods=["POST"])
def toggle_shopping_item(item_id):
    if not MEALIE_URL or not MEALIE_API_TOKEN:
        return jsonify({"error": "Mealie not configured"}), 400
    try:
        item = mealie_request("GET", f"/api/households/shopping/items/{item_id}")
        item["checked"] = not item.get("checked", False)
        mealie_request("PUT", f"/api/households/shopping/items/{item_id}", item)
        return jsonify({"success": True, "checked": item["checked"]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/shopping-list/delete/<item_id>", methods=["POST"])
def delete_shopping_item(item_id):
    if not MEALIE_URL or not MEALIE_API_TOKEN:
        return jsonify({"error": "Mealie not configured"}), 400
    try:
        mealie_request("DELETE", f"/api/households/shopping/items/{item_id}")
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/shopping-list")
def shopping_list_view():
    if not MEALIE_URL or not MEALIE_API_TOKEN or not MEALIE_SHOPPING_LIST_ID:
        return Response("<h1>Mealie not configured</h1>", mimetype="text/html")
    try:
        data = mealie_request("GET", f"/api/households/shopping/lists/{MEALIE_SHOPPING_LIST_ID}")
        items = data.get("listItems", [])
    except Exception as e:
        return Response(f"<h1>Couldn't load shopping list</h1><p>{e}</p>", mimetype="text/html")

    rows = ""
    for item in items:
        checked_attr = "checked" if item.get("checked") else ""
        text_style = "text-decoration:line-through;opacity:0.5;" if item.get("checked") else ""
        note = item.get("note") or item.get("display") or ""
        item_id = item.get("id", "")
        rows += f'''<li style="{text_style}" data-item-id="{item_id}">
            <input type="checkbox" onchange="toggleItem('{item_id}', this)" {checked_attr}>
            <span class="item-text">{note}</span>
            <button class="del-btn" onclick="deleteItem('{item_id}', this)">✕</button>
        </li>\n'''

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Shopping List</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{ font-family: sans-serif; background:#171B27; color:#F5F0E8; padding:24px; }}
            h1 {{ color:#E8B84B; }}
            ul {{ list-style:none; padding:0; }}
            li {{ background:#252B3D; padding:12px 16px; margin-bottom:8px; border-radius:10px;
                  display:flex; align-items:center; gap:12px; }}
            .item-text {{ flex:1; }}
            input[type="checkbox"] {{ width:20px; height:20px; cursor:pointer; flex-shrink:0; }}
            .del-btn {{ background:none; border:none; color:#B7B2AA; font-size:18px;
                        cursor:pointer; padding:2px 6px; flex-shrink:0; }}
            .del-btn:hover {{ color:#E8654A; }}
        </style>
    </head>
    <body>
        <h1>🛒 Shopping List</h1>
        <ul id="list">{rows if rows else '<li>List is empty</li>'}</ul>
        <script>
            async function toggleItem(id, checkbox) {{
                const li = checkbox.closest('li');
                try {{
                    const res = await fetch('/shopping-list/toggle/' + id, {{ method: 'POST' }});
                    const data = await res.json();
                    if (data.success) {{
                        li.style.textDecoration = data.checked ? 'line-through' : 'none';
                        li.style.opacity = data.checked ? '0.5' : '1';
                    }} else {{
                        checkbox.checked = !checkbox.checked;
                        alert('Could not update item.');
                    }}
                }} catch(e) {{
                    checkbox.checked = !checkbox.checked;
                    alert('Could not update item.');
                }}
            }}

            async function deleteItem(id, btn) {{
                const li = btn.closest('li');
                try {{
                    const res = await fetch('/shopping-list/delete/' + id, {{ method: 'POST' }});
                    const data = await res.json();
                    if (data.success) {{
                        li.remove();
                    }} else {{
                        alert('Could not delete item.');
                    }}
                }} catch(e) {{
                    alert('Could not delete item.');
                }}
            }}
        </script>
    </body>
    </html>
    """
    return Response(html, mimetype="text/html")


@app.route("/")
def index():
    with open(os.path.join(os.path.dirname(__file__), "index.html")) as f:
        return Response(f.read(), mimetype="text/html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5500)
