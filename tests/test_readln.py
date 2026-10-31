"""
The questions a mod will ask, read before installing (GUI-AUDIT M8 item 48,
ADR-0049). Measured on 105 mods of the reference build (tools/readln_census.py,
docs/TESTING.md): these cases are the shapes found there.
"""
from iemod_fetch.readln import scan

TP2 = """BACKUP ~mymod/backup~
AUTHOR ~me~
VERSION ~v2~
LANGUAGE ~English~ ~english~ ~mymod/tra/english/setup.tra~
LANGUAGE ~Italiano~ ~italian~ ~mymod/tra/italian/setup.tra~
"""
TRA_EN = "@1 = ~Which portraits do you want? 1. Original 2. New~\n@2 = ~Enter a percentage:~\n"
TRA_IT = "@1 = ~Quali ritratti vuoi? 1. Originali 2. Nuovi~\n@2 = ~Inserisci una percentuale:~\n"


def files(tp2_body: str, **extra) -> dict[str, str]:
    out = {"mymod/setup-mymod.tp2": TP2 + tp2_body,
           "mymod/tra/english/setup.tra": TRA_EN, "mymod/tra/italian/setup.tra": TRA_IT}
    # mymod__lib__x_tpa -> mymod/lib/x.tpa
    out.update({k.replace("__", "/")[::-1].replace("_", ".", 1)[::-1]: v
                for k, v in extra.items()})
    return out


def test_a_question_in_a_component_is_keyed_by_its_tra_string():
    found = scan("mymod/setup-mymod.tp2", files("""
BEGIN @10 DESIGNATED 100
  PRINT @1
  ACTION_READLN portraits
BEGIN @11 DESIGNATED 200
  COPY_EXISTING ~sw1h01.itm~ ~override~
"""))
    [prompt] = found.of(100)
    assert prompt.ref == "@1" and prompt.key == "@1"
    assert prompt.text.startswith("Which portraits do you want?")
    assert prompt.variable == "portraits" and prompt.line == 9
    assert not prompt.conditional and not prompt.repeats
    assert found.of(200) == []


def test_the_text_is_the_chosen_languages_the_key_is_not():
    body = "\nBEGIN @10\n  PRINT @2\n  ACTION_READLN chance\n"
    english = scan("mymod/setup-mymod.tp2", files(body), language_index=0).of(0)[0]
    italian = scan("mymod/setup-mymod.tp2", files(body), language_index=1).of(0)[0]
    assert english.text == "Enter a percentage:"
    assert italian.text == "Inserisci una percentuale:"
    assert english.key == italian.key == "@2"


def test_questions_in_a_launched_function_and_an_included_file_are_the_components():
    found = scan("mymod/setup-mymod.tp2", files("""
ALWAYS
  INCLUDE ~%MOD_FOLDER%/lib/functions.tph~
END
BEGIN @10
  LAF ask_portraits END
BEGIN @11
  ACTION_INCLUDE ~%MOD_FOLDER%/lib/chance.tpa~
""", mymod__lib__functions_tph="""
DEFINE_ACTION_FUNCTION ask_portraits BEGIN
  PRINT @1
  ACTION_READLN portraits
END
""", mymod__lib__chance_tpa="PRINT @2\nACTION_READLN chance\n"))
    assert [(p.ref, p.via) for p in found.of(0)] == [("@1", "function ask_portraits")]
    assert [(p.ref, p.via, p.file) for p in found.of(1)] == [
        ("@2", "include %MOD_FOLDER%/lib/chance.tpa", "mymod/lib/chance.tpa")]
    assert found.unread == []


def test_a_file_named_after_the_component_number_is_the_one_read():
    """Tweaks Anthology: `cdtweaks/lib/comp_%COMPONENT_NUMBER%_prompts.tpa`,
    in its ALWAYS block - WeiDU runs ALWAYS before each component."""
    found = scan("mymod/setup-mymod.tp2", files("""
ALWAYS
  ACTION_IF FILE_EXISTS ~mymod/lib/comp_%COMPONENT_NUMBER%_prompts.tpa~ BEGIN
    INCLUDE ~mymod/lib/comp_%COMPONENT_NUMBER%_prompts.tpa~
  END
END
BEGIN @10 DESIGNATED 3183
BEGIN @11 DESIGNATED 3184
""", mymod__lib__comp_3183_prompts_tpa="PRINT @1\nACTION_READLN portraits\n"))
    [prompt] = found.of(3183)
    assert prompt.via == "always" and prompt.conditional
    assert found.of(3184) == []
    assert found.unread == []          # 3184 has none: FILE_EXISTS guards it


def test_a_question_asked_until_valid_and_one_asked_only_sometimes():
    found = scan("mymod/setup-mymod.tp2", files("""
BEGIN @10
  OUTER_SET valid = 0
  OUTER_WHILE (valid = 0) BEGIN
    PRINT @2
    ACTION_READLN chance
    ACTION_IF IS_AN_INT chance BEGIN OUTER_SET valid = 1 END
  END
  ACTION_IF NOT FILE_EXISTS ~mymod/prefs.txt~ BEGIN
    PRINT @1
    ACTION_READLN portraits
  END
"""))
    asked = found.of(0)
    assert [(p.ref, p.repeats, p.conditional) for p in asked] == [
        ("@2", True, False), ("@1", False, True)]


def test_a_path_built_at_install_time_is_said_unread_not_guessed():
    """SCS includes its SFO library through %sfo_loc%, set while installing."""
    found = scan("mymod/setup-mymod.tp2", files("""
BEGIN @10
  OUTER_SPRINT sfo_loc ~lib~
  INCLUDE ~%MOD_FOLDER%/%sfo_loc%/tools.tpa~
"""))
    assert found.of(0) == []
    assert found.unread == ["include %MOD_FOLDER%/%sfo_loc%/tools.tpa (a path built from variables)"]


def test_a_constant_set_before_the_components_builds_a_path():
    """EEUITweaks: `OUTER_SPRINT PKGNAME ~EEUITweaks~`, then
    `INCLUDE ~%PKGNAME%/include/...~`."""
    found = scan("mymod/setup-mymod.tp2", files("""
OUTER_SPRINT PKGNAME ~mymod~
BEGIN @10
  INCLUDE ~%PKGNAME%/include/update.tpa~
""", mymod__include__update_tpa="PRINT @1\nACTION_READLN portraits\n"))
    assert [p.ref for p in found.of(0)] == ["@1"]


def test_a_file_written_inside_the_tp2_is_read():
    found = scan("mymod/setup-mymod.tp2", files("""
BEGIN @10
  ACTION_INCLUDE ~./inlined/ask.tpa~
<<<<<<<< ./inlined/ask.tpa
PRINT @2
ACTION_READLN chance
>>>>>>>>
"""))
    assert [p.ref for p in found.of(0)] == ["@2"]


def test_a_question_printed_as_text_has_no_ref_and_keys_by_its_text():
    found = scan("mymod/setup-mymod.tp2", files("""
BEGIN @10
  PRINT ~Press a key to continue~
  ACTION_READLN dummy
"""))
    [prompt] = found.of(0)
    assert prompt.ref == "" and prompt.key == "Press a key to continue"


def test_a_function_calling_itself_does_not_loop():
    found = scan("mymod/setup-mymod.tp2", files("""
DEFINE_ACTION_FUNCTION again BEGIN
  PRINT @1
  ACTION_READLN portraits
  LAF again END
END
BEGIN @10
  LAF again END
"""))
    assert [p.ref for p in found.of(0)] == ["@1"]


def test_weidus_own_functions_are_not_reported():
    found = scan("mymod/setup-mymod.tp2", files("""
BEGIN @10
  LAF HANDLE_CHARSETS INT_VAR infer_charsets = 1 END
"""))
    assert found.of(0) == [] and found.unread == []


def test_a_tp2_not_given_is_said_so():
    found = scan("mymod/setup-mymod.tp2", {})
    assert found.components == {} and found.unread == ["mymod/setup-mymod.tp2 (not given)"]
