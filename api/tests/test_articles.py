from app.api import articles as a


def test_only_plain_slugs_in_the_articles_folder_are_served(client, tmp_path, monkeypatch):
    (tmp_path / "first-article.md").write_text("# First\n\n> A short summary.\n\nBody text with `code`.\n", encoding="utf-8")
    (tmp_path / "_order.txt").write_text("first-article\n", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("not an article", encoding="utf-8")
    monkeypatch.setattr(a, "ARTICLES_DIR", tmp_path)
    lst = client.get("/api/docs/articles").json()["articles"]
    assert [x["slug"] for x in lst] == ["first-article"] and lst[0]["title"] == "First" and lst[0]["summary"] == "A short summary."
    got = client.get("/api/docs/articles/first-article").json()
    assert "Body text" in got["markdown"] and got["minutes"] >= 1
    assert client.get("/api/docs/articles/secret").status_code == 404
    assert client.get("/api/docs/articles/..%2f..%2fsecrets").status_code in (404, 422)
    assert client.get("/api/docs/articles/NOT_VALID").status_code == 404
