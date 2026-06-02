# SPDX-License-Identifier: AGPL-3.0-or-later
import os
from app import create_app

app = create_app()

if __name__ == "__main__":
    # TSPB_DEBUG only relaxes the Secure-cookie flag for plain-HTTP dev (see
    # create_app). The interactive Werkzeug debugger is remote-code-exec, so it
    # is a SEPARATE explicit opt-in and is only ever bound to loopback — never
    # conflate "dev cookies" with "exposed debugger".
    use_debugger = os.environ.get("TSPB_FLASK_DEBUG", "").lower() in ("1", "true", "yes")
    host = "127.0.0.1" if use_debugger else "0.0.0.0"
    app.run(host=host, port=8000, debug=use_debugger)
