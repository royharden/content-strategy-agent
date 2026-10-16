"""Local server configuration guards; these checks never open a listener."""

import pytest

from content_strategy.cli import main


def arguments(tmp_path, port="21300"):
    return [
        "serve",
        "--database",
        str(tmp_path / "review.sqlite3"),
        "--call-database",
        str(tmp_path / "calls.sqlite3"),
        "--namespace",
        "test",
        "--assets",
        str(tmp_path / "assets"),
        "--port",
        port,
    ]


def test_server_refuses_out_of_band_port_before_start(tmp_path):
    with pytest.raises(SystemExit) as error:
        main(arguments(tmp_path, "8000"))
    assert error.value.code == 2 and not (tmp_path / "review.sqlite3").exists()


def test_server_requires_built_assets_and_no_database_effect(tmp_path):
    assert main(arguments(tmp_path)) == 2
    assert not (tmp_path / "review.sqlite3").exists()


def test_server_host_and_proxy_configuration_remain_local(tmp_path, monkeypatch):
    import uvicorn

    folder = tmp_path / "assets"
    folder.mkdir()
    (folder / "index.html").write_text("<main>fixture</main>")
    calls = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **options: calls.append(options))
    assert main(arguments(tmp_path)) == 0
    assert len(calls) == 1
    assert calls[0]["host"] == "127.0.0.1" and calls[0]["port"] == 21300
    assert calls[0]["proxy_headers"] is False and calls[0]["access_log"] is False
    assert not (tmp_path / "review.sqlite3").exists()
