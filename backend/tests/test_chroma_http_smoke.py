"""Optional real HTTP integration test; no external service or model key required.

Run with RUN_CHROMA_HTTP_SMOKE=1 using the backend virtual environment.
A separate local Chroma process uses a temporary directory and an ephemeral port.
"""

import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx

from app.services.vector_store import ChromaVectorStore
from app.services import vector_store
from app.common.exceptions import BusinessException


@unittest.skipUnless(os.environ.get("RUN_CHROMA_HTTP_SMOKE") == "1", "optional local Chroma HTTP test")
class ChromaHttpSmokeTest(unittest.TestCase):
    def setUp(self):
        import chromadb

        self.chromadb = chromadb
        self.directory = tempfile.TemporaryDirectory(prefix="library-chroma-smoke-")
        self.addCleanup(self.cleanup_directory)
        self.server_output = tempfile.TemporaryFile(mode="w+b")
        self.addCleanup(self.server_output.close)
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            self.port = reservation.getsockname()[1]
        self.server = None
        self.addCleanup(self.stop_server)
        self.start_server()

    def cleanup_directory(self):
        # Windows may briefly retain HNSW file handles after process termination.
        for attempt in range(3):
            try:
                self.directory.cleanup()
                return
            except PermissionError:
                if attempt == 2:
                    raise
                time.sleep(0.5 * (attempt + 1))

    def start_server(self):
        executable = Path(sys.executable).with_name("chroma.exe" if os.name == "nt" else "chroma")
        self.server = subprocess.Popen(
            [str(executable), "run", "--path", self.directory.name, "--host", "127.0.0.1", "--port", str(self.port)],
            stdin=subprocess.DEVNULL,
            stdout=self.server_output,
            stderr=self.server_output,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        deadline = time.monotonic() + 25
        with httpx.Client(timeout=0.5, trust_env=False) as health_client:
            while time.monotonic() < deadline:
                if self.server.poll() is not None:
                    break
                try:
                    response = health_client.get(f"http://127.0.0.1:{self.port}/api/v2/heartbeat")
                    if response.status_code == 200:
                        return
                except httpx.TransportError:
                    pass
                time.sleep(0.1)
        self.server_output.seek(0)
        self.fail("Chroma server failed to start:\n" + self.server_output.read().decode("utf-8", errors="replace"))

    def stop_server(self):
        if self.server is not None and self.server.poll() is None:
            self.server.terminate()
            try:
                self.server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.server.kill()
                self.server.wait(timeout=5)

    def client(self):
        config = SimpleNamespace(CHROMA_HOST="127.0.0.1", CHROMA_PORT=self.port, CHROMA_TIMEOUT_SECONDS=2.0)
        with patch.object(vector_store, "settings", config):
            client = ChromaVectorStore()._get_client()
        self.addCleanup(client.close)
        return client

    def test_tenant_initialization_is_bounded_when_http_server_does_not_respond(self):
        release = threading.Event()

        class StalledHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                release.wait(5)

            def log_message(self, format, *args):
                pass

        stalled = ThreadingHTTPServer(("127.0.0.1", 0), StalledHandler)
        thread = threading.Thread(target=stalled.serve_forever, daemon=True)
        thread.start()

        def cleanup_stalled_server():
            release.set()
            stalled.shutdown()
            stalled.server_close()
            thread.join(timeout=2)

        self.addCleanup(cleanup_stalled_server)
        config = SimpleNamespace(
            CHROMA_HOST="127.0.0.1", CHROMA_PORT=stalled.server_port, CHROMA_TIMEOUT_SECONDS=0.1
        )
        started = time.monotonic()
        with patch.object(vector_store, "settings", config):
            with self.assertRaises(BusinessException) as raised:
                ChromaVectorStore().query("library-smoke", [1.0, 0.0])
        self.assertEqual(raised.exception.code, 503)
        self.assertLess(time.monotonic() - started, 2.0)

    def test_explicit_cosine_vectors_survive_restart_and_version_delete(self):
        client = self.client()
        store = ChromaVectorStore(client=client)
        self.assertEqual(store.query("missing-collection", [1.0, 0.0]), [])
        store.upsert(
            "library-smoke",
            ["chunk-1", "chunk-2"],
            ["预约规则", "开放时间"],
            [[1.0, 0.0], [0.0, 1.0]],
            [{"version_id": 1}, {"version_id": 2}],
        )
        store.upsert(
            "library-smoke", ["chunk-1"], ["预约规则新版"], [[1.0, 0.0]], [{"version_id": 1}]
        )
        collection = client.get_collection("library-smoke", embedding_function=None)
        self.assertEqual(collection.count(), 2)
        self.assertEqual(collection.configuration["hnsw"]["space"], "cosine")
        matches = store.query("library-smoke", [1.0, 0.0], limit=2)
        self.assertEqual(matches[0]["id"], "chunk-1")
        self.assertAlmostEqual(matches[0]["distance"], 0.0, places=6)
        self.assertEqual(matches[0]["metadata"]["version_id"], "1")

        self.stop_server()
        self.start_server()
        store = ChromaVectorStore(client=self.client())
        self.assertEqual(len(store.query("library-smoke", [1.0, 0.0], limit=2)), 2)
        store.delete_version("library-smoke", 1)
        remaining = store.query("library-smoke", [1.0, 0.0], limit=2)
        self.assertEqual([match["id"] for match in remaining], ["chunk-2"])
        store.delete_version("library-smoke", 1)
        store.delete_version("missing-collection", 1)


if __name__ == "__main__":
    unittest.main()
