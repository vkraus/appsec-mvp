"""Deliberately-vulnerable seed application A. DO NOT deploy."""

import os
import sqlite3
from flask import Flask, request

app = Flask(__name__)


@app.route("/search")
def search():
    # CWE-89: SQL injection — both SonarQube and Semgrep detect this on this line.
    query = request.args.get("q", "")
    conn = sqlite3.connect("data.db")
    rows = conn.execute(f"SELECT * FROM items WHERE name = '{query}'").fetchall()
    return {"rows": rows}


@app.route("/ping")
def ping():
    # CWE-78: OS command injection — both SonarQube and Semgrep detect this on this line.
    host = request.args.get("host", "")
    os.system(f"ping -c 1 {host}")
    return "ok"
