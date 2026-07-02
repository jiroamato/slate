import json

from slate import output
from slate.output import SlateError


def test_exit_code_constants():
    assert output.EXIT_OK == 0
    assert output.EXIT_UNEXPECTED == 1
    assert output.EXIT_USAGE == 2
    assert output.EXIT_DEDUP == 3
    assert output.EXIT_LOCK == 4
    assert output.EXIT_NO_STORE == 5


def test_slate_error_defaults_to_validation_exit_2():
    err = SlateError("bad input")
    assert err.code == "validation"
    assert err.exit_code == output.EXIT_USAGE
    assert err.hint is None
    assert err.retry is None
    assert str(err) == "bad input"


def test_emit_json_envelope(capsys):
    output.emit({"created": True}, json_mode=True, command="init")
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"ok": True, "command": "init", "created": True}


def test_emit_text_mode_prints_text_only(capsys):
    output.emit({"created": True}, json_mode=False, command="init", text="Initialized .slate/")
    assert capsys.readouterr().out == "Initialized .slate/\n"


def test_fail_json_envelope_and_exit_code(capsys):
    err = SlateError(
        "no store found",
        code="no_store",
        exit_code=output.EXIT_NO_STORE,
        hint="run slate init to create one",
        retry="slate init",
    )
    assert output.fail(err, json_mode=True) == 5
    payload = json.loads(capsys.readouterr().err)
    assert payload == {
        "ok": False,
        "error": {
            "code": "no_store",
            "message": "no store found",
            "hint": "run slate init to create one",
            "retry": "slate init",
        },
    }


def test_fail_text_names_problem_hint_and_retry(capsys):
    err = SlateError("bad type", hint="valid types: convention, pattern", retry="slate record x --type pattern")
    code = output.fail(err, json_mode=False)
    assert code == 2
    err_out = capsys.readouterr().err
    assert "error: bad type" in err_out
    assert "hint: valid types: convention, pattern" in err_out
    assert "retry: slate record x --type pattern" in err_out


def test_fail_text_omits_missing_hint_retry(capsys):
    output.fail(SlateError("boom"), json_mode=False)
    err_out = capsys.readouterr().err
    assert err_out == "error: boom\n"
