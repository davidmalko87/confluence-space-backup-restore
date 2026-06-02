# Tests for confluence_tool.config.ConfluenceConfig validation/normalization
from confluence_tool.config import ConfluenceConfig


def _cfg(**kw):
    base = dict(confluence_url="https://acme.atlassian.net/wiki",
                email="me@example.com", api_token="tok")
    base.update(kw)
    return ConfluenceConfig(**base)


def test_valid_config_has_no_errors():
    assert _cfg().validate() == []


def test_url_gets_wiki_suffix_appended():
    c = _cfg(confluence_url="https://acme.atlassian.net")
    assert c.validate() == []
    assert c.confluence_url == "https://acme.atlassian.net/wiki"


def test_url_trailing_slash_stripped():
    c = _cfg(confluence_url="https://acme.atlassian.net/wiki/")
    c.validate()
    assert c.confluence_url == "https://acme.atlassian.net/wiki"


def test_missing_url_is_error():
    c = _cfg(confluence_url="")
    assert any("CONFLUENCE_URL" in e for e in c.validate())


def test_token_without_email_is_error():
    c = _cfg(email="")
    assert any("CONFLUENCE_EMAIL" in e for e in c.validate())


def test_no_auth_is_error():
    c = _cfg(api_token="", email="", cookie_header="")
    assert any("API_TOKEN" in e or "COOKIE" in e for e in c.validate())


def test_cookie_auth_is_accepted():
    c = _cfg(api_token="", email="", cookie_header="session=abc")
    assert c.validate() == []


def test_page_size_bounds():
    assert any("PAGE_SIZE" in e for e in _cfg(page_size=0).validate())
    assert any("PAGE_SIZE" in e for e in _cfg(page_size=251).validate())
    assert _cfg(page_size=250).validate() == []


def test_body_format_validated():
    assert any("BODY_FORMAT" in e for e in _cfg(body_format="view").validate())
    assert _cfg(body_format="atlas_doc_format").validate() == []


def test_site_origin_and_slug():
    c = _cfg(confluence_url="https://acme.atlassian.net/wiki")
    c.validate()
    assert c.site_origin == "https://acme.atlassian.net"
    assert c.site_slug == "acme"
