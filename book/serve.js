#!/usr/bin/env node
// Serves the book pages locally, wrapped the way the artifact host wraps them.
//   node book/serve.js [port]
// The page files are fragments (no <!doctype>/<html>/<head>), same as published
// artifacts, so this server adds the skeleton, a CSS reset and a theme toggle.

import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const DIR = path.dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.argv[2]) || 8787;

const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".md": "text/plain; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".svg": "image/svg+xml"
};

const RESET = `*,*::before,*::after{box-sizing:border-box}
body{margin:0}img,svg{max-width:100%}
#themebtn{position:fixed;right:14px;top:14px;z-index:99;font:600 11px/1 ui-monospace,monospace;
letter-spacing:.1em;padding:8px 11px;border:1px solid currentColor;border-radius:3px;
background:transparent;color:inherit;cursor:pointer;opacity:.55}
#themebtn:hover{opacity:1}
@media print{#themebtn{display:none}}`;

const TOGGLE = `<button id="themebtn">THEME</button><script>
(function(){var b=document.getElementById("themebtn"),r=document.documentElement;
var s=localStorage.getItem("bookTheme");if(s)r.setAttribute("data-theme",s);
b.addEventListener("click",function(){
  var cur=r.getAttribute("data-theme");
  if(!cur)cur=matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light";
  var next=cur==="dark"?"light":"dark";
  r.setAttribute("data-theme",next);localStorage.setItem("bookTheme",next);});})();
</script>`;

function wrap(fragment, name) {
  if (/^\s*<!doctype/i.test(fragment)) return fragment;
  const m = fragment.match(/<title>([\s\S]*?)<\/title>/i);
  const title = m ? m[1] : name;
  return `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>${title}</title><style>${RESET}</style></head><body>
${fragment}
${TOGGLE}
</body></html>`;
}

function index() {
  const files = fs.readdirSync(DIR).filter(f => f.endsWith(".html")).sort();
  const rows = files.map(f => {
    const src = fs.readFileSync(path.join(DIR, f), "utf8");
    const t = src.match(/<title>([\s\S]*?)<\/title>/i);
    const kb = Math.round(fs.statSync(path.join(DIR, f)).size / 1024);
    return `<li><a href="/${f}">${f}</a><span>${t ? t[1] : ""}</span><em>${kb} KB</em></li>`;
  }).join("");
  return wrap(`<title>book — local</title>
<style>
:root{--p:#F2F3EF;--i:#141A20;--m:#7C8792;--r:#D3D7CE}
@media(prefers-color-scheme:dark){:root{--p:#12151A;--i:#E6E9E4;--m:#6E7883;--r:#272D35}}
:root[data-theme="dark"]{--p:#12151A;--i:#E6E9E4;--m:#6E7883;--r:#272D35}
:root[data-theme="light"]{--p:#F2F3EF;--i:#141A20;--m:#7C8792;--r:#D3D7CE}
body{background:var(--p);color:var(--i);font:16px/1.55 system-ui,sans-serif;padding:60px 28px}
.w{max-width:760px;margin:0 auto}
h1{font:600 30px/1.15 Georgia,serif;margin:0 0 6px}
p{color:var(--m);margin:0 0 30px;font-size:13.5px}
ul{list-style:none;margin:0;padding:0;border-top:1px solid var(--r)}
li{display:grid;grid-template-columns:190px 1fr auto;gap:14px;align-items:baseline;
padding:13px 0;border-bottom:1px solid var(--r)}
a{color:inherit;font:600 17px/1.2 Georgia,serif}
span{color:var(--m);font-size:13px}
em{color:var(--m);font:10px ui-monospace,monospace;font-style:normal;letter-spacing:.08em}
@media(max-width:620px){li{grid-template-columns:1fr}}
</style>
<div class="w"><h1>book</h1>
<p>Origin layers, served from <code>${DIR}</code>. Print any page to PDF with Ctrl/Cmd-P.</p>
<ul>${rows}</ul></div>`, "book");
}

http.createServer((req, res) => {
  const name = decodeURIComponent(req.url.split("?")[0]).replace(/^\/+/, "");
  if (!name || name === "index.html") {
    res.writeHead(200, { "content-type": TYPES[".html"] });
    return res.end(index());
  }
  const file = path.join(DIR, name);
  if (!file.startsWith(DIR + path.sep) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
    res.writeHead(404, { "content-type": "text/plain" });
    return res.end("not found: " + name);
  }
  const ext = path.extname(file);
  const body = fs.readFileSync(file, ext === ".html" ? "utf8" : null);
  res.writeHead(200, {
    "content-type": TYPES[ext] || "application/octet-stream",
    "cache-control": "no-store"
  });
  res.end(ext === ".html" ? wrap(body, name) : body);
}).listen(PORT, "127.0.0.1", () => {
  console.log("book → http://127.0.0.1:" + PORT + "/");
  fs.readdirSync(DIR).filter(f => f.endsWith(".html")).sort()
    .forEach(f => console.log("        http://127.0.0.1:" + PORT + "/" + f));
});
