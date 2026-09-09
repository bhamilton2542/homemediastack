from flask import Flask, jsonify, request, Response, session
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import os
import functools

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-key-in-production")

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "clanabout.db")

DEFAULT_DISCORD_URL = "https://discord.gg/xPzhAT9uyA"
DEFAULT_VOTE_URL = "http://192.168.6.2:5600"
DEFAULT_CLAN_NAME = "XP4ME"
DEFAULT_FOUNDER_NAME = "SuckAFreeTyt"
DEFAULT_FOUNDER_BIO = "Founder bio coming soon. Command has not yet filed this record."
DEFAULT_RULES_TEXT = "1. Respect all squad members.\n2. No cheating or exploiting.\n3. Communicate clearly during ops.\n\nFull rules coming soon."


def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS site_content (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            discord_url TEXT NOT NULL,
            vote_url TEXT NOT NULL,
            founder_name TEXT NOT NULL,
            founder_bio TEXT NOT NULL,
            rules_text TEXT NOT NULL
        )
    """)
    try:
        conn.execute("ALTER TABLE site_content ADD COLUMN clan_name TEXT NOT NULL DEFAULT 'XP4ME'")
    except sqlite3.OperationalError:
        pass
    conn.execute("""
        CREATE TABLE IF NOT EXISTS admin_auth (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            password_hash TEXT NOT NULL,
            must_change_password INTEGER NOT NULL DEFAULT 1
        )
    """)

    if conn.execute("SELECT COUNT(*) as c FROM site_content").fetchone()["c"] == 0:
        conn.execute(
            "INSERT INTO site_content (id, discord_url, vote_url, clan_name, founder_name, founder_bio, rules_text) "
            "VALUES (1, ?, ?, ?, ?, ?, ?)",
            (DEFAULT_DISCORD_URL, DEFAULT_VOTE_URL, DEFAULT_CLAN_NAME, DEFAULT_FOUNDER_NAME, DEFAULT_FOUNDER_BIO, DEFAULT_RULES_TEXT),
        )

    if conn.execute("SELECT COUNT(*) as c FROM admin_auth").fetchone()["c"] == 0:
        conn.execute(
            "INSERT INTO admin_auth (id, password_hash, must_change_password) VALUES (1, ?, 1)",
            (generate_password_hash("admin123"),),
        )
        print("Seeded default edit-access password: admin123 -- CHANGE THIS")

    conn.commit()
    conn.close()


def admin_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("is_admin"):
            return jsonify({"error": "Not authorized"}), 401
        return f(*args, **kwargs)
    return wrapper


@app.route("/api/content", methods=["GET"])
def get_content():
    conn = get_db()
    row = conn.execute("SELECT * FROM site_content WHERE id = 1").fetchone()
    conn.close()
    return jsonify(dict(row))


@app.route("/api/content", methods=["POST"])
@admin_required
def update_content():
    data = request.json or {}
    conn = get_db()
    conn.execute(
        """UPDATE site_content SET discord_url = ?, vote_url = ?, clan_name = ?, founder_name = ?,
           founder_bio = ?, rules_text = ? WHERE id = 1""",
        (
            data.get("discord_url", "").strip(),
            data.get("vote_url", "").strip(),
            data.get("clan_name", "").strip(),
            data.get("founder_name", "").strip(),
            data.get("founder_bio", "").strip(),
            data.get("rules_text", "").strip(),
        ),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/login", methods=["POST"])
def login():
    data = request.json or {}
    password = data.get("password", "")

    conn = get_db()
    auth = conn.execute("SELECT * FROM admin_auth WHERE id = 1").fetchone()
    conn.close()

    if not auth or not check_password_hash(auth["password_hash"], password):
        return jsonify({"error": "Incorrect password"}), 401

    session["is_admin"] = True
    return jsonify({"ok": True, "must_change_password": bool(auth["must_change_password"])})


@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/me", methods=["GET"])
def me():
    conn = get_db()
    auth = conn.execute("SELECT must_change_password FROM admin_auth WHERE id = 1").fetchone()
    conn.close()
    return jsonify({
        "is_admin": bool(session.get("is_admin")),
        "must_change_password": bool(auth["must_change_password"]) if (auth and session.get("is_admin")) else False,
    })


@app.route("/api/change-password", methods=["POST"])
@admin_required
def change_password():
    data = request.json or {}
    current_password = data.get("current_password", "")
    new_password = data.get("new_password", "")

    if not new_password or len(new_password) < 4:
        return jsonify({"error": "New password must be at least 4 characters"}), 400

    conn = get_db()
    auth = conn.execute("SELECT * FROM admin_auth WHERE id = 1").fetchone()

    if not auth or not check_password_hash(auth["password_hash"], current_password):
        conn.close()
        return jsonify({"error": "Current password is incorrect"}), 401

    conn.execute(
        "UPDATE admin_auth SET password_hash = ?, must_change_password = 0 WHERE id = 1",
        (generate_password_hash(new_password),),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/")
def index():
    with open(os.path.join(os.path.dirname(__file__), "index.html")) as f:
        return Response(f.read(), mimetype="text/html")


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5700)
