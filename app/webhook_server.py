"""Part 4 student implementation."""

import json

import logging

import os

from concurrent.futures import ThreadPoolExecutor

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from pathlib import Path

from tempfile import TemporaryDirectory

from app.integration import process_request

from app.webex_client import WEBEX_API_BASE, WebexClient

class WebexEventHandler:
    def __init__(self, client, bot_person_id, processor=None):
        self.client = client
        self.bot_person_id = bot_person_id
        self.processor = processor or process_request

    def handle_event(self, event):
        if not isinstance(event, dict):
            return None
        data = event.get("data")
        if (
            event.get("resource") != "messages"
            or event.get("event") != "created"
            or not isinstance(data, dict)
            or not isinstance(data.get("id"), str)
            or not data["id"]
        ):
            return None
        if data.get("personId") == self.bot_person_id:
            return None

        message = self.client.get_message(data["id"])
        if not isinstance(message, dict) or message.get("personId") == self.bot_person_id:
            return None
        room_id = message.get("roomId")
        if not isinstance(room_id, str) or not room_id:
            return None

        attachments = message.get("files")
        if attachments is None:
            attachments = []
        elif not isinstance(attachments, list):
            return None
        if len(attachments) > 1:
            result = {"status": "error", "result": "multiple_attachments"}
        elif not attachments:
            result = self.processor(
                message.get("mentionedPeople"),
                None,
                self.bot_person_id,
            )
        else:
            if not isinstance(attachments[0], str) or not attachments[0]:
                return None
            with TemporaryDirectory() as directory:
                attachment_path = Path(directory) / "request.yaml"
                attachment_path.write_bytes(
                    self.client.download_file(attachments[0])
                )
                result = self.processor(
                    message.get("mentionedPeople"),
                    attachment_path,
                    self.bot_person_id,
                )

        self.client.send_message(
            room_id,
            json.dumps(result, separators=(",", ":")),
        )
        return result

def make_http_handler(submit_event):
    class WebhookHandler(BaseHTTPRequestHandler):
        def _send_json(self, status, payload):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path != "/health":
                self._send_json(404, {"status": "error", "result": "not_found"})
                return
            self._send_json(200, {"status": "ok", "result": "healthy"})

        def do_POST(self):
            if self.path != "/webhook":
                self._send_json(404, {"status": "error", "result": "not_found"})
                return
            try:
                length = int(self.headers.get("Content-Length", ""))
            except (TypeError, ValueError):
                self._send_json(400, {"status": "error", "result": "invalid_event"})
                return
            if length < 1 or length > 1_000_000:
                self._send_json(400, {"status": "error", "result": "invalid_event"})
                return
            try:
                body = self.rfile.read(length)
                event = json.loads(body)
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send_json(400, {"status": "error", "result": "invalid_event"})
                return
            if not isinstance(event, dict):
                self._send_json(400, {"status": "error", "result": "invalid_event"})
                return

            submit_event(event)
            self._send_json(200, {"status": "ok", "result": "accepted"})

    return WebhookHandler

def main():
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    client = WebexClient()
    identity_response = client.session.get(
        f"{WEBEX_API_BASE}/people/me",
        headers=client.headers,
        timeout=10,
    )
    identity_response.raise_for_status()
    bot_person_id = identity_response.json().get("id")
    if not isinstance(bot_person_id, str) or not bot_person_id:
        raise RuntimeError("Webex did not return the bot person ID")

    event_handler = WebexEventHandler(client, bot_person_id)
    executor = ThreadPoolExecutor(max_workers=1)

    def submit_event(event):
        future = executor.submit(event_handler.handle_event, event)

        def report_failure(completed):
            error = completed.exception()
            if error is not None:
                logging.exception(
                    "Failed to process Webex event",
                    exc_info=(type(error), error, error.__traceback__),
                )

        future.add_done_callback(report_failure)

    host = os.getenv("WEBHOOK_HOST", "0.0.0.0")
    port = int(os.getenv("WEBHOOK_PORT", "8000"))
    server = ThreadingHTTPServer((host, port), make_http_handler(submit_event))
    try:
        logging.info("Starting webhook server on %s:%s", host, port)
        server.serve_forever()
    finally:
        server.server_close()
        executor.shutdown(wait=True)

if __name__ == "__main__":
    main()
