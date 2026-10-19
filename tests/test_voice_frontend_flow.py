"""
Runs tests/js/voice_flow.js: the REAL voice-assistant.js / receipt-camera.js
driven in a simulated browser (jsdom) against this app running on a live
local server, with a scripted fake microphone. Skipped automatically if Node
or the jsdom dev-dependency isn't installed (`cd tests/js && npm install`).
"""
import os
import shutil
import subprocess
import threading

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
JS_DIR = os.path.join(HERE, "js")
NODE = shutil.which("node")
HAS_JSDOM = os.path.isdir(os.path.join(JS_DIR, "node_modules", "jsdom"))


@pytest.mark.skipif(not NODE or not HAS_JSDOM, reason="needs Node and `npm install` in tests/js")
def test_voice_entry_frontend_flow_in_jsdom(app):
    from werkzeug.serving import make_server

    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = subprocess.run(
            [NODE, "voice_flow.js", f"http://127.0.0.1:{server.server_port}"],
            cwd=JS_DIR, capture_output=True, text=True, timeout=120,
        )
    finally:
        server.shutdown()
    assert result.returncode == 0, "front-end flow failed:\n" + result.stdout + result.stderr
