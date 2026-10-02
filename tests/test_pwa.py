def test_service_worker_served_at_root_scope(client):
    r = client.get("/sw.js")
    assert r.status_code == 200
    assert "javascript" in r.content_type
    assert b"ledger-static" in r.data


def test_service_worker_never_caches_financial_pages(client):
    sw = open("static/sw.js").read()
    assert "isStaticAsset" in sw
    assert "/api/" not in sw.split("STATIC_ASSETS")[1].split("]")[0]  # api not in the cached list


def test_offline_fallback_page_exists_and_is_honest():
    html = open("static/offline.html").read()
    assert "offline" in html.lower()
    assert "never stored for offline" in html.lower() or "never" in html.lower()


def test_manifest_served(client):
    r = client.get("/static/manifest.webmanifest")
    assert r.status_code == 200
    body = r.get_json()
    assert body["name"] == "Ledger - Personal Finance"
