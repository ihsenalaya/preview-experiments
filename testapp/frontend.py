"""Simple HTML frontend — served when APP_MODE=frontend on port 3000."""
import os
from flask import Flask, render_template_string

BACKEND_URL = os.environ.get("BACKEND_URL", "http://svc-backend:8080")
PR_NUMBER   = os.environ.get("PREVIEW_PR", "?")
BRANCH      = os.environ.get("PREVIEW_BRANCH", "main")

_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Exp App — PR #{{ pr }}</title>
  <style>
    body { font-family: sans-serif; margin: 2rem; }
    #products { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px,1fr)); gap: 1rem; margin-top:1rem; }
    .card { border:1px solid #ccc; border-radius:6px; padding:1rem; cursor:pointer; }
    .card:hover { background:#f5f5f5; }
    #detail { display:none; position:fixed; top:10%; left:50%; transform:translateX(-50%);
              background:#fff; border:2px solid #333; border-radius:8px; padding:2rem; min-width:300px; }
    #close-btn { margin-top:1rem; }
    .badge { background:#0072B2; color:#fff; padding:2px 8px; border-radius:4px; font-size:.8rem; }
    #filter { margin:.5rem 0; }
  </style>
</head>
<body>
  <h1>Catalogue <span class="badge">PR #{{ pr }} · {{ branch }}</span></h1>
  <label>Min discount %:
    <input id="filter" type="number" value="0" min="0" max="100">
  </label>
  <button onclick="applyFilter()">Filter</button>
  <div id="products">Loading…</div>

  <div id="detail">
    <h2 id="d-name"></h2>
    <p>Price: €<span id="d-price"></span></p>
    <p>Discount: <span id="d-discount"></span>%</p>
    <section id="related-section">
      <h3>Related</h3>
      <ul id="d-related"></ul>
    </section>
    <button id="close-btn" onclick="closeDetail()">Close</button>
  </div>

  <script>
    const API = "{{ backend }}";
    let allProducts = [];

    async function loadProducts(minDiscount) {
      const url = minDiscount > 0
        ? API + "/api/products/discounted?min_discount=" + minDiscount
        : API + "/api/products";
      const r = await fetch(url);
      const data = await r.json();
      allProducts = Array.isArray(data) ? data : (data.products || []);
      render(allProducts);
    }

    function render(products) {
      const el = document.getElementById("products");
      if (!products.length) { el.innerHTML = "<p>No products.</p>"; return; }
      el.innerHTML = products.map(p =>
        `<div class="card" onclick="openDetail(${p.id})">
          <strong>${p.name}</strong><br>€${p.price}
          ${p.discount_pct > 0 ? `<br><em>${p.discount_pct}% off</em>` : ""}
        </div>`
      ).join("");
    }

    async function openDetail(id) {
      const [prod, rel] = await Promise.all([
        fetch(API + "/api/products/" + id).then(r=>r.json()),
        fetch(API + "/api/products/" + id + "/related").then(r=>r.json()),
      ]);
      document.getElementById("d-name").textContent    = prod.name;
      document.getElementById("d-price").textContent   = prod.price;
      document.getElementById("d-discount").textContent = prod.discount_pct;
      const relList = document.getElementById("d-related");
      relList.innerHTML = (rel.products||[]).map(p=>`<li>${p.name}</li>`).join("") || "<li>None</li>";
      document.getElementById("detail").style.display = "block";
    }

    function closeDetail() { document.getElementById("detail").style.display = "none"; }

    function applyFilter() {
      loadProducts(parseInt(document.getElementById("filter").value)||0);
    }

    loadProducts(0);
  </script>
</body>
</html>
"""


def run_frontend():
    fapp = Flask(__name__)

    @fapp.get("/")
    def index():
        return render_template_string(_HTML, pr=PR_NUMBER, branch=BRANCH, backend=BACKEND_URL)

    @fapp.get("/healthz")
    def healthz():
        return "ok"

    fapp.run(host="0.0.0.0", port=3000)


if __name__ == "__main__":
    run_frontend()
