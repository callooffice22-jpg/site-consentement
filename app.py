from flask import Flask, request, render_template, redirect, url_for, send_file, abort
import sqlite3, uuid, csv, io, os
from datetime import datetime, timezone

app = Flask(__name__)
DB = "consentements.db"

def init_db():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS prospects (
            id TEXT PRIMARY KEY,
            email TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS consentements (
            proof_id TEXT PRIMARY KEY,
            prospect_id TEXT NOT NULL,
            email TEXT NOT NULL,
            consent TEXT NOT NULL,
            timestamp_utc TEXT NOT NULL,
            ip TEXT,
            user_agent TEXT,
            referrer TEXT,
            FOREIGN KEY(prospect_id) REFERENCES prospects(id)
        )
    """)
    con.commit()
    con.close()

def get_ip():
    # Compatible avec un reverse proxy (Render, Railway, etc.)
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr

@app.route("/")
def home():
    return render_template("home.html")

@app.route("/create", methods=["POST"])
def create_link():
    email = (request.form.get("email") or "").strip().lower()
    if not email or "@" not in email:
        return "Adresse e-mail invalide", 400

    prospect_id = str(uuid.uuid4())
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute(
        "INSERT INTO prospects (id, email, created_at) VALUES (?, ?, ?)",
        (prospect_id, email, datetime.now(timezone.utc).isoformat())
    )
    con.commit()
    con.close()

    link = request.host_url.rstrip("/") + url_for("consent", prospect_id=prospect_id)
    return render_template("link_created.html", email=email, link=link)

@app.route("/c/<prospect_id>", methods=["GET", "POST"])
def consent(prospect_id):
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("SELECT email FROM prospects WHERE id = ?", (prospect_id,))
    row = cur.fetchone()

    if not row:
        con.close()
        abort(404)

    email = row[0]

    cur.execute("SELECT proof_id, consent, timestamp_utc FROM consentements WHERE prospect_id = ?", (prospect_id,))
    existing = cur.fetchone()

    if request.method == "POST":
        if existing:
            con.close()
            return render_template(
                "already_answered.html",
                consent=existing[1],
                timestamp=existing[2],
                proof_id=existing[0]
            )

        answer = (request.form.get("consent") or "").upper()
        if answer not in ("OUI", "NON"):
            con.close()
            return "Réponse invalide", 400

        proof_id = "PRV-" + uuid.uuid4().hex[:12].upper()
        timestamp = datetime.now(timezone.utc).isoformat()
        ip = get_ip()
        user_agent = request.headers.get("User-Agent", "")
        referrer = request.headers.get("Referer", "")

        cur.execute("""
            INSERT INTO consentements
            (proof_id, prospect_id, email, consent, timestamp_utc, ip, user_agent, referrer)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (proof_id, prospect_id, email, answer, timestamp, ip, user_agent, referrer))
        con.commit()
        con.close()

        return render_template(
            "thanks.html",
            consent=answer,
            proof_id=proof_id,
            timestamp=timestamp
        )

    con.close()
    return render_template("consent.html", email=email)

@app.route("/admin")
def admin():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("""
        SELECT proof_id, email, consent, timestamp_utc, ip, user_agent
        FROM consentements
        ORDER BY timestamp_utc DESC
    """)
    rows = cur.fetchall()
    con.close()
    return render_template("admin.html", rows=rows)

@app.route("/admin/export.csv")
def export_csv():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("""
        SELECT proof_id, email, consent, timestamp_utc, ip, user_agent, referrer
        FROM consentements
        ORDER BY timestamp_utc DESC
    """)
    rows = cur.fetchall()
    con.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID preuve", "Email", "Consentement", "Horodatage UTC", "IP", "Navigateur", "Referrer"])
    writer.writerows(rows)

    mem = io.BytesIO(output.getvalue().encode("utf-8-sig"))
    mem.seek(0)
    return send_file(mem, mimetype="text/csv", as_attachment=True, download_name="consentements.csv")

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
