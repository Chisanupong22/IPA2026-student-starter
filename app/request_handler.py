from collections.abc import Mapping

import yaml

from app.core import validate_request


def _error(result):
    return {"status": "error", "result": result}


def validate_webex_envelope(
    mentioned_people,
    attachment_path,
    bot_person_id,
):
    """
    Validate the target bot's actual mention and YAML attachment.
    Return an error response, or None when the envelope is valid.
    """
    if (
        not isinstance(bot_person_id, str)
        or not bot_person_id
        or not isinstance(mentioned_people, list)
        or bot_person_id not in mentioned_people
    ):
        return _error("missing_bot_mention")
    if attachment_path is None:
        return _error("no_yaml")
    return None


def handle_webex_request(
    mentioned_people,
    attachment_path,
    bot_person_id,
):
    """
    Validate the envelope, then validate the attached YAML request.
    Return a response dictionary. Do not dispatch to a router.
    """
    envelope_error = validate_webex_envelope(
        mentioned_people,
        attachment_path,
        bot_person_id,
    )
    if envelope_error is not None:
        return envelope_error

    try:
        with open(attachment_path, encoding="utf-8") as request_file:
            data = yaml.safe_load(request_file)
    except (OSError, UnicodeError, yaml.YAMLError):
        return _error("invalid_yaml")

    if not isinstance(data, Mapping):
        return _error("invalid_yaml")
    return validate_request(data)
