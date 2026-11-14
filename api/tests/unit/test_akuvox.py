"""The Akuvox settings file (app/akuvox.py): an intercom that reads cards for the controller, takes calls, and never opens the door itself."""
from __future__ import annotations

from app import akuvox

D = akuvox.Device(id="ic-1", name="Front door\nintercom", relay_target="10.152.0.20:8742", relay_secret="Secret123", admin_password="AdminPw9",
                  provision_url="https://link.entry.photonind.com/provision/v1/tok/", sip_server="vox.example", sip_user="door-101",
                  sip_password="sipPw")


def keys(text: str) -> dict:
    out = {}
    for line in text.splitlines():
        if line and not line.startswith("#"):
            k, _, v = line.partition(" = ")
            assert k not in out, f"{k} twice"
            out[k] = v
    return out


def test_a_card_reader_that_never_opens_the_door_itself():
    k = keys(akuvox.render(D))
    assert k["Config.DoorSetting.GENERAL.WiegandMode"] == "1" and k["Config.DoorSetting.GENERAL.WiegandType"] == "1"      # 34-bit out
    assert k["Config.DoorSetting.GENERAL.WiegandOutVerify"] == "0"                                                        # the controller decides
    for key in ("WiegandOpenRelayA", "WiegandOpenRelayB", "TamperOptions"):
        assert k[f"Config.DoorSetting.GENERAL.{key}"] == "0"
    assert k["Config.DoorSetting.RELAY.DTMFUnlock"] == "0" and k["Config.DoorSetting.DTMF.WhitelistEnable"] == "0"
    assert k["Config.DoorSetting.WEBRELAY.RelayType"] == "1"                                                              # web relay only


def test_unlock_from_a_call_and_the_events_go_to_entry_link():
    k = keys(akuvox.render(D))
    assert k["Config.DoorSetting.WEBRELAY.WebRelay_Action_1"] == "http://10.152.0.20:8742/v1/relay?intercom=ic-1&key=Secret123"
    assert k["Config.DoorSetting.WEBRELAY.WebRelay_Key_1"] == "#" == k["Config.DoorSetting.DTMF.Code1"]
    assert k["Config.DoorSetting.WEBRELAY.IpAddress"] == "" and k["Config.DoorSetting.WEBRELAY.AuthorizationMode"] == "0"
    assert k["Config.Features.ACTIONURL.Enable"] == "1"
    assert k["Config.Features.ACTIONURL.MakeCall"].endswith("/v1/event?intercom=ic-1&key=Secret123&kind=call_start&remote=$remote")
    assert k["Config.Features.ACTIONURL.HangUp"].endswith("kind=call_end&remote=$remote")
    assert k["Config.Features.ACTIONURL.TamperAlarmTriggered"].endswith("kind=tamper")


def test_calls_provisioning_and_its_own_password():
    k = keys(akuvox.render(D))
    assert k["Config.Account1.GENERAL.Enable"] == "1" and k["Config.Account1.GENERAL.UserName"] == "door-101" == k["Config.Account1.GENERAL.AuthName"]
    assert k["Config.Account1.GENERAL.Pwd"] == "sipPw" and k["Config.Account1.SIP.Server"] == "vox.example" and k["Config.Account1.SIP.Port"] == "5061"
    assert k["Config.Account1.SIP.TransType"] == "2" and k["Config.Account1.ENCRYPTION.SRTPEncryption"] == "2"
    assert k["Config.Account1.GENERAL.Label"] == "Front door intercom"                                    # a line break cannot start a new key
    assert k["Config.Autoprovision.GENERAL.Url"] == D.provision_url and k["Config.Autoprovision.MODE.Mode"] == "4"
    assert k["Config.Autoprovision.PNP.Enable"] == "0" and k["Config.Settings.WEB_LOGIN.Password"] == "AdminPw9"


def test_without_a_sip_account_or_a_controller_address_those_parts_are_off():
    k = keys(akuvox.render(akuvox.Device(id="ic-2", name="Gate", relay_target="", relay_secret="s", admin_password="a",
                                         provision_url="https://x/", sip_transport="udp")))
    assert k["Config.Account1.GENERAL.Enable"] == "0" and k["Config.Account1.SIP.TransType"] == "0"
    assert k["Config.Account1.ENCRYPTION.SRTPEncryption"] == "0"
    assert k["Config.DoorSetting.WEBRELAY.RelayType"] == "0" and k["Config.DoorSetting.WEBRELAY.WebRelay_Action_1"] == ""
    assert k["Config.Features.ACTIONURL.Enable"] == "0" and k["Config.Features.ACTIONURL.MakeCall"] == ""


def test_secrets_are_plain_letters_and_digits():
    p = akuvox.new_password()
    assert len(p) == 24 and p.isalnum() and p != akuvox.new_password()
    assert len(akuvox.token_hash("x")) == 64
    assert akuvox.general_file("r000000000532.cfg").startswith("#")
