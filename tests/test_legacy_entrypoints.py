import pytest

import server  # noqa: F401 - importing registers the static entrypoint routes


@pytest.mark.parametrize(
    ("path", "target"),
    (
        ("/reports.html", "/?page=reports"),
        ("/audit-logs.html", "/?page=settings&settings_tab=audit-logs"),
        ("/batch-qr.html", "/?page=orders"),
    ),
)
def test_retired_html_entrypoints_redirect_to_supported_spa_pages(
    client, path, target
):
    response = client.get(path, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"] == target


@pytest.mark.parametrize(
    "path",
    (
        "/mobile.html",
        "/mobile_inspection.html",
        "/board.html",
        "/bigscreen.html",
        "/offline.html",
    ),
)
def test_supported_standalone_html_entrypoints_remain_available(client, path):
    assert client.get(path).status_code == 200


def test_unknown_html_entrypoint_is_not_rendered_by_catch_all(client):
    assert client.get("/removed-legacy-page.html").status_code == 404
