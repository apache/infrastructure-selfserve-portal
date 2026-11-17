"""Startup HTML compilation (master template + SRI) and static file serving."""

import base64
import hashlib
import pathlib
import re

import pytest

import app as selfserve


def before_serving_hook(application, name):
    (hook,) = [f for f in application.before_serving_funcs if f.__name__ == name]
    return hook


@pytest.fixture
def compiled(application, monkeypatch, tmp_path):
    """Run the app's compile_html startup hook into a temp dir instead of htdocs/compiled."""
    monkeypatch.setattr(selfserve, "COMPILED_DIR", str(tmp_path / "compiled"))
    return before_serving_hook(application, "compile_html"), tmp_path / "compiled"


async def test_compile_wraps_every_page_in_master_template(compiled):
    hook, outdir = compiled
    await hook()
    pages = sorted(p.name for p in outdir.iterdir())
    assert "index.html" in pages and "mailinglist-new.html" in pages
    page = (outdir / "mailinglist-new.html").read_text()
    assert page.startswith("<!doctype html>")
    assert "Create a mailing list" in page
    assert "{contents}" not in page


async def test_compile_adds_subresource_integrity(compiled):
    hook, outdir = compiled
    await hook()
    script = (pathlib.Path(selfserve.STATIC_DIR) / "js" / "selfserve.js").read_bytes()
    expected = "sha384-" + base64.b64encode(hashlib.sha384(script).digest()).decode()
    assert f'integrity="{expected}"' in (outdir / "index.html").read_text()


async def test_serves_compiled_html_and_static_assets(client, compiled):
    hook, _outdir = compiled
    await hook()
    for path in ("/", "/index.html"):
        resp = await client.get(path)
        assert resp.status_code == 200
        assert "<!doctype html>" in await resp.get_data(as_text=True)
    js = await client.get("/js/selfserve.js")
    assert js.status_code == 200
    assert (await client.get("/no-such-file.css")).status_code == 404


async def test_script_urls_change_with_their_contents(compiled, monkeypatch, tmp_path):
    """A changed script gets a new URL, so a browser's cached old copy can't fail the new SRI check."""
    hook, outdir = compiled
    await hook()
    first = re.search(r'src="/js/selfserve\.js\?v=(\w+)" integrity="sha384-', (outdir / "index.html").read_text())
    assert first

    static = tmp_path / "htdocs"
    (static / "js").mkdir(parents=True)
    (static / "index.html").write_bytes((pathlib.Path(selfserve.STATIC_DIR) / "index.html").read_bytes())
    (static / "js" / "selfserve.js").write_text("// changed\n")
    monkeypatch.setattr(selfserve, "STATIC_DIR", str(static))
    await hook()
    second = re.search(r'src="/js/selfserve\.js\?v=(\w+)"', (outdir / "index.html").read_text())
    assert second and second.group(1) != first.group(1)


async def test_pages_are_revalidated_and_assets_cached(client, compiled):
    hook, _outdir = compiled
    await hook()
    page = await client.get("/index.html")
    assert "no-cache" in page.headers["Cache-Control"]
    assert (await client.get("/index.html", headers={"If-None-Match": page.headers["ETag"]})).status_code == 304
    js = await client.get("/js/selfserve.js?v=anything")
    assert js.status_code == 200
    assert "no-cache" not in js.headers["Cache-Control"] and "max-age=43200" in js.headers["Cache-Control"]
