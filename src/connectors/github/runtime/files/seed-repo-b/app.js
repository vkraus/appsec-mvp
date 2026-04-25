// Deliberately-vulnerable seed application B. DO NOT deploy.

const express = require("express");
const fs = require("fs");
const path = require("path");
const app = express();

app.get("/greet", (req, res) => {
  // CWE-79: reflected XSS — both SonarQube and Semgrep detect this on this line.
  const name = req.query.name || "";
  res.send(`<h1>Hello, ${name}</h1>`);
});

app.get("/file", (req, res) => {
  // CWE-22: path traversal — both SonarQube and Semgrep detect this on this line.
  const name = req.query.name || "";
  const content = fs.readFileSync(path.join("/data", name), "utf8");
  res.send(content);
});

app.listen(3000);
