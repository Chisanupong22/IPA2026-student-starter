"""Part 4 student implementation."""

from collections.abc import Mapping
from pathlib import Path

import yaml

from app.core import validate_request
from app.dispatcher import dispatch_request

from app.request_handler import validate_webex_envelope

def process_request(mentioned_people, attachment_path, bot_person_id):
    envelope_error = validate_webex_envelope(
        mentioned_people,
        attachment_path,
        bot_person_id,
    )
    if envelope_error is not None:
        return envelope_error

    try:
        with Path(attachment_path).open(encoding="utf-8") as request_file:
            data = yaml.safe_load(request_file)
    except (OSError, UnicodeError, yaml.YAMLError):
        return {"status": "error", "result": "invalid_yaml"}
    if not isinstance(data, Mapping):
        return {"status": "error", "result": "invalid_yaml"}

    validation = validate_request(data)
    if validation["status"] == "error":
        return validation
    return dispatch_request(data)
