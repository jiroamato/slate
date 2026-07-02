from slate.cli import main


def test_version_flag_prints_version_and_exits_zero(capsys):
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == "slate 0.1.0"
