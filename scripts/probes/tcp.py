"""Run inside a container: try TCP connections given as host:port arguments.

Prints one line per target: "<target> open" or "<target> blocked (<reason>)".
"""

import socket
import sys

for target in sys.argv[1:]:
    host, port = target.rsplit(":", 1)
    try:
        socket.create_connection((host, int(port)), timeout=3).close()
        print(f"{target} open")
    except OSError as exc:
        print(f"{target} blocked ({exc.strerror or exc})")
