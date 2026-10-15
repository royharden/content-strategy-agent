import json

from content_strategy.cli import main


def csv_bytes():
    return (
        b"post_id,date,platform,text,impressions,likes,comments,shares\n"
        b"p1,2026-10-14,x,hello,10,1,0,0\n"
    )


def test_actual_cli_import_then_restart_historical_report_without_approval(tmp_path, capsys):
    source, database = tmp_path / "input.csv", tmp_path / "local.sqlite3"
    source.write_bytes(csv_bytes())
    common = ["--database", str(database), "--namespace", "user"]
    assert main(["import-csv", *common, "--file", str(source)]) == 0
    imported = json.loads(capsys.readouterr().out)
    assert imported["rows"] == 1 and imported["retained_only"]
    assert imported["activation_or_approval"] is False
    assert (
        main(
            [
                "report",
                *common,
                "--dataset-id",
                imported["dataset_id"],
                "--snapshot-id",
                imported["snapshot_id"],
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["report_sha256"] == imported["report_sha256"]
    assert report["snapshot"]["snapshot_id"] == imported["snapshot_id"]
    assert report["platforms"][0]["platform"] == "x"


def test_invalid_file_has_no_database_or_partial_runtime_effect(tmp_path, capsys):
    source, database = tmp_path / "input.csv", tmp_path / "absent.sqlite3"
    source.write_bytes(csv_bytes() + b"broken\n")
    assert (
        main(
            [
                "import-csv",
                "--database",
                str(database),
                "--namespace",
                "user",
                "--file",
                str(source),
            ]
        )
        == 2
    )
    assert json.loads(capsys.readouterr().out)["error"] == "invalid_csv"
    assert not database.exists()


def test_missing_report_database_and_unknown_namespace_do_not_leak_content(tmp_path, capsys):
    database = tmp_path / "absent"
    assert (
        main(
            [
                "report",
                "--database",
                str(database),
                "--namespace",
                "user",
                "--dataset-id",
                "s9-dataset-" + "a" * 32,
                "--snapshot-id",
                "b" * 64,
            ]
        )
        == 2
    )
    assert json.loads(capsys.readouterr().out) == {"error": "database_not_found"}
    assert not database.exists()
