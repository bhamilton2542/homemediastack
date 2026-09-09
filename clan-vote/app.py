from flask import Flask, jsonify, request, Response, session
from werkzeug.security import generate_password_hash, check_password_hash
from apscheduler.schedulers.background import BackgroundScheduler
import sqlite3
import os
import functools
import urllib.request
import json
import datetime

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-key-in-production")

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "clanvote.db")
DISCORD_PROMOTION_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
DISCORD_NEW_VOTE_WEBHOOK_URL = os.environ.get("DISCORD_NEW_VOTE_WEBHOOK_URL", "")

APPROVAL_THRESHOLD = 0.75
SUSTAIN_HOURS = 48
DEFAULT_PROMOTED_PASSWORD = "1234"
CLAN_MEMBER_ROLE_ID = "1396639973045698651"
PUBLIC_VOTE_SITE_URL = "https://vote.xp4me.com"


def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_admin INTEGER NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    try:
        conn.execute("ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 1")
    except sqlite3.OperationalError:
        pass

    conn.execute("""
        CREATE TABLE IF NOT EXISTS nominees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            note TEXT,
            submitted_by TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    try:
        conn.execute("ALTER TABLE nominees ADD COLUMN first_qualified_at TEXT")
    except sqlite3.OperationalError:
        pass
    conn.execute("""
        CREATE TABLE IF NOT EXISTS votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            nominee_id INTEGER NOT NULL,
            vote INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, nominee_id),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(nominee_id) REFERENCES nominees(id) ON DELETE CASCADE
        )
    """)

    existing = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()
    if existing["c"] == 0:
        conn.execute(
            "INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, 1)",
            ("admin", generate_password_hash("admin123")),
        )
        conn.commit()
        print("Seeded default admin account: admin / admin123 -- CHANGE THIS PASSWORD")

    conn.commit()
    conn.close()


def login_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"error": "Not logged in"}), 401
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"error": "Not logged in"}), 401
        if not session.get("is_admin"):
            return jsonify({"error": "Admin access required"}), 403
        return f(*args, **kwargs)
    return wrapper


@app.route("/api/login", methods=["POST"])
def login():
    data = request.json or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")

    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()

    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "Invalid username or password"}), 401

    session["user_id"] = user["id"]
    session["username"] = user["username"]
    session["is_admin"] = bool(user["is_admin"])

    return jsonify({
        "username": user["username"],
        "is_admin": bool(user["is_admin"]),
        "must_change_password": bool(user["must_change_password"]),
    })


@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/me", methods=["GET"])
def me():
    if "user_id" not in session:
        return jsonify({"logged_in": False})

    conn = get_db()
    user = conn.execute("SELECT must_change_password FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    conn.close()

    return jsonify({
        "logged_in": True,
        "username": session["username"],
        "is_admin": session["is_admin"],
        "must_change_password": bool(user["must_change_password"]) if user else False,
    })


@app.route("/api/change-password", methods=["POST"])
@login_required
def change_password():
    data = request.json or {}
    current_password = data.get("current_password", "")
    new_password = data.get("new_password", "")

    if not new_password or len(new_password) < 4:
        return jsonify({"error": "New password must be at least 4 characters"}), 400

    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()

    if not user or not check_password_hash(user["password_hash"], current_password):
        conn.close()
        return jsonify({"error": "Current password is incorrect"}), 401

    conn.execute(
        "UPDATE users SET password_hash = ?, must_change_password = 0 WHERE id = ?",
        (generate_password_hash(new_password), session["user_id"]),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/nominees", methods=["GET"])
@login_required
def get_nominees():
    conn = get_db()
    nominees = conn.execute("SELECT * FROM nominees ORDER BY created_at DESC").fetchall()

    result = []
    for n in nominees:
        approve = conn.execute(
            "SELECT COUNT(*) as c FROM votes WHERE nominee_id = ? AND vote = 1", (n["id"],)
        ).fetchone()["c"]
        deny = conn.execute(
            "SELECT COUNT(*) as c FROM votes WHERE nominee_id = ? AND vote = 0", (n["id"],)
        ).fetchone()["c"]
        my_vote_row = conn.execute(
            "SELECT vote FROM votes WHERE nominee_id = ? AND user_id = ?",
            (n["id"], session["user_id"]),
        ).fetchone()
        my_vote = None if my_vote_row is None else bool(my_vote_row["vote"])

        hours_remaining = None
        if n["first_qualified_at"] is not None:
            qualified_since = datetime.datetime.fromisoformat(n["first_qualified_at"])
            elapsed_hours = (datetime.datetime.utcnow() - qualified_since).total_seconds() / 3600
            hours_remaining = max(0, round(SUSTAIN_HOURS - elapsed_hours, 1))

        result.append({
            "id": n["id"],
            "name": n["name"],
            "note": n["note"],
            "submitted_by": n["submitted_by"],
            "created_at": n["created_at"],
            "approve": approve,
            "deny": deny,
            "my_vote": my_vote,
            "hours_remaining": hours_remaining,
        })

    conn.close()
    return jsonify(result)


@app.route("/api/nominees", methods=["POST"])
@admin_required
def add_nominee():
    data = request.json or {}
    name = data.get("name", "").strip()
    note = data.get("note", "").strip()

    if not name:
        return jsonify({"error": "Name required"}), 400

    conn = get_db()
    conn.execute(
        "INSERT INTO nominees (name, note, submitted_by) VALUES (?, ?, ?)",
        (name, note, session["username"]),
    )
    conn.commit()
    conn.close()
    notify_new_vote(name, note, session["username"])
    return jsonify({"ok": True})


@app.route("/api/nominees/<int:nominee_id>", methods=["DELETE"])
@admin_required
def delete_nominee(nominee_id):
    conn = get_db()
    conn.execute("DELETE FROM nominees WHERE id = ?", (nominee_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/vote", methods=["POST"])
@login_required
def cast_vote():
    data = request.json or {}
    nominee_id = data.get("nominee_id")
    vote = data.get("vote")

    if nominee_id is None or vote is None:
        return jsonify({"error": "nominee_id and vote required"}), 400

    conn = get_db()
    conn.execute(
        """INSERT INTO votes (user_id, nominee_id, vote) VALUES (?, ?, ?)
           ON CONFLICT(user_id, nominee_id) DO UPDATE SET vote = excluded.vote""",
        (session["user_id"], nominee_id, 1 if vote else 0),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/users", methods=["GET"])
@admin_required
def list_users():
    conn = get_db()
    users = conn.execute("SELECT id, username, is_admin, created_at FROM users ORDER BY username").fetchall()
    conn.close()
    return jsonify([dict(u) for u in users])


@app.route("/api/users", methods=["POST"])
@admin_required
def add_user():
    data = request.json or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")
    is_admin = bool(data.get("is_admin", False))

    if not username or not password:
        return jsonify({"error": "Username and password required"}), 400

    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, ?)",
            (username, generate_password_hash(password), 1 if is_admin else 0),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"error": "Username already exists"}), 400
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/users/<int:user_id>", methods=["DELETE"])
@admin_required
def delete_user(user_id):
    if user_id == session["user_id"]:
        return jsonify({"error": "Cannot delete your own account"}), 400
    conn = get_db()
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/")
def index():
    with open(os.path.join(os.path.dirname(__file__), "index.html")) as f:
        return Response(f.read(), mimetype="text/html")


def send_discord_embed(webhook_url, title, description, color, context_label, content=None):
    if not webhook_url:
        print(f"[{context_label}] No webhook configured, skipping notification")
        return
    payload = {
        "embeds": [{
            "title": title,
            "description": description,
            "color": color,
        }]
    }
    if content:
        payload["content"] = content
    try:
        req = urllib.request.Request(
            webhook_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (compatible; ClanVoteBot/1.0)",
            },
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"[{context_label}] Discord notification failed: {e}")


def notify_promotion(nominee_name):
    send_discord_embed(
        DISCORD_PROMOTION_WEBHOOK_URL,
        "NEW OFFICIAL MEMBER",
        f"**{nominee_name}** has cleared review and is now an official clan member.",
        9426266,
        "promotion",
    )


def notify_new_vote(nominee_name, note, submitted_by):
    note_line = f"\n\n*{note}*" if note else ""
    mention_content = f"<@&{CLAN_MEMBER_ROLE_ID}> A new vote is open — cast yours here: {PUBLIC_VOTE_SITE_URL}"
    send_discord_embed(
        DISCORD_NEW_VOTE_WEBHOOK_URL,
        "NEW VOTE OPEN",
        f"**{nominee_name}** has been filed for review by {submitted_by}. Head to the review board to cast your vote.{note_line}",
        14196257,
        "new-vote",
        content=mention_content,
    )


def unique_username(conn, base_name):
    candidate = base_name
    suffix = 2
    while conn.execute("SELECT 1 FROM users WHERE username = ?", (candidate,)).fetchone():
        candidate = f"{base_name}_{suffix}"
        suffix += 1
    return candidate


def check_and_promote_nominees():
    conn = get_db()
    try:
        nominees = conn.execute("SELECT * FROM nominees").fetchall()
        admin_ids = [row["id"] for row in conn.execute("SELECT id FROM users WHERE is_admin = 1").fetchall()]

        for n in nominees:
            approve = conn.execute(
                "SELECT COUNT(*) as c FROM votes WHERE nominee_id = ? AND vote = 1", (n["id"],)
            ).fetchone()["c"]
            deny = conn.execute(
                "SELECT COUNT(*) as c FROM votes WHERE nominee_id = ? AND vote = 0", (n["id"],)
            ).fetchone()["c"]
            total = approve + deny

            meets_percentage = total > 0 and (approve / total) >= APPROVAL_THRESHOLD

            if admin_ids:
                placeholders = ",".join("?" * len(admin_ids))
                admin_approvals = conn.execute(
                    f"SELECT COUNT(*) as c FROM votes WHERE nominee_id = ? AND vote = 1 AND user_id IN ({placeholders})",
                    [n["id"]] + admin_ids,
                ).fetchone()["c"]
                all_admins_approved = admin_approvals == len(admin_ids)
            else:
                all_admins_approved = False

            qualifies_now = meets_percentage and all_admins_approved

            if n["first_qualified_at"] is None:
                if qualifies_now:
                    conn.execute(
                        "UPDATE nominees SET first_qualified_at = ? WHERE id = ?",
                        (datetime.datetime.utcnow().isoformat(), n["id"]),
                    )
                    conn.commit()
                continue

            qualified_since = datetime.datetime.fromisoformat(n["first_qualified_at"])
            elapsed_hours = (datetime.datetime.utcnow() - qualified_since).total_seconds() / 3600

            if elapsed_hours >= SUSTAIN_HOURS:
                username = unique_username(conn, n["name"])
                conn.execute(
                    "INSERT INTO users (username, password_hash, is_admin, must_change_password) VALUES (?, ?, 0, 1)",
                    (username, generate_password_hash(DEFAULT_PROMOTED_PASSWORD)),
                )
                conn.execute("DELETE FROM nominees WHERE id = ?", (n["id"],))
                conn.commit()
                print(f"[promotion] Promoted '{n['name']}' to member account '{username}'")
                notify_promotion(n["name"])
    finally:
        conn.close()


scheduler = BackgroundScheduler()
scheduler.add_job(check_and_promote_nominees, "interval", hours=1, id="promotion_check")
scheduler.start()

init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5600)
