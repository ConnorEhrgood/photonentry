"""JSON logs (app/obs.py): one object per line, with the request id and organization when known, and the error when there is one."""
import io
import json
import logging

from app import obs


def test_a_log_line_is_one_json_object_with_the_request_id():
    stream = io.StringIO()
    h = logging.StreamHandler(stream)
    h.setFormatter(obs.JsonFormatter("api"))
    log = logging.getLogger("photonentry.test-obs")
    log.handlers[:] = [h]
    log.propagate = False
    t1, t2 = obs.request_id.set("req-12345678"), obs.org_id.set("org-1")
    try:
        log.warning("door %s refused", "front")
        try:
            raise ValueError("boom")
        except ValueError:
            log.exception("failed")
    finally:
        obs.request_id.reset(t1)
        obs.org_id.reset(t2)
    first, second = [json.loads(line) for line in stream.getvalue().splitlines() if line.startswith("{")]
    assert (first["level"], first["service"], first["msg"], first["request_id"], first["org_id"]) == ("warning", "api", "door front refused", "req-12345678", "org-1")
    assert "ValueError: boom" in second["error"]


def test_configure_sends_everything_to_stdout_as_json():
    obs.configure("worker")
    root = logging.getLogger()
    assert len(root.handlers) == 1 and isinstance(root.handlers[0].formatter, obs.JsonFormatter)
    assert logging.getLogger("uvicorn.access").propagate is True
    assert obs.take_request_id(None) != obs.take_request_id(None) and obs.take_request_id("abcdefgh") == "abcdefgh"


def test_secret_addresses_are_cut_out_of_access_log_lines():
    """An intercom's provisioning token and a visitor's pass token are in their addresses: uvicorn's access log would write them out."""
    stream = io.StringIO()
    h = logging.StreamHandler(stream)
    h.setFormatter(obs.JsonFormatter("api"))
    log = logging.getLogger("photonentry.test-obs-redact")
    log.handlers[:] = [h]
    log.propagate = False
    log.info('%s - "%s %s HTTP/1.1" %d', "10.0.0.5:4711", "GET", "/provision/v1/-TdpEHH51bDNa_QAECD/0250DE000101.cfg", 200)
    log.info('%s - "%s %s HTTP/1.1" %d', "10.0.0.5:4711", "GET", "/passes/v1/AbC-123_xyz", 200)
    log.info('%s - "%s %s HTTP/1.1" %d', "10.0.0.5:4711", "GET", "/passes/v1/AbC?x=1", 404)
    lines = [json.loads(line)["msg"] for line in stream.getvalue().splitlines()]
    assert lines == ['10.0.0.5:4711 - "GET /provision/v1/…/0250DE000101.cfg HTTP/1.1" 200', '10.0.0.5:4711 - "GET /passes/v1/… HTTP/1.1" 200',
                     '10.0.0.5:4711 - "GET /passes/v1/…?x=1 HTTP/1.1" 404']
    assert obs.redact("/tenants/t1/sites/s1/passes") == "/tenants/t1/sites/s1/passes"
