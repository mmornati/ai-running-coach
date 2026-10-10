"""Serveurs HTTP de test sans résolution DNS inverse au démarrage.

`http.server.HTTPServer.server_bind` appelle `socket.getfqdn(host)` pour remplir
`server_name`, que les faux services des tests n'utilisent jamais. Sur les
runners macOS de GitHub, cet appel bloque ~35 s (mesuré) : le premier test de
chaque processus qui lançait un faux serveur payait ce délai. Même correctif
que `arc_serve.Server` et le serveur de `arc_chat.make_server`.

Remplacements directs : `from tests.lib.local_http import ThreadingHTTPServer`.
"""

from __future__ import annotations

import http.server
import socketserver


class _NoFqdnBind:
    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = port


class HTTPServer(_NoFqdnBind, http.server.HTTPServer):
    pass


class ThreadingHTTPServer(_NoFqdnBind, http.server.ThreadingHTTPServer):
    pass
