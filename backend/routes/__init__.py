"""HTTP route blueprints and small request helpers shared by them."""

from flask import request

from ..errors import ValidationError


def json_body():
    """Return the request's JSON object or raise a 400 ValidationError."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValidationError(
            "Request body must be a JSON object (send the header "
            "'Content-Type: application/json').")
    return data


def bool_arg(name, default):
    raw = request.args.get(name)
    if raw is None:
        return default
    if raw.lower() in ("1", "true", "yes"):
        return True
    if raw.lower() in ("0", "false", "no"):
        return False
    raise ValidationError("Invalid '%s'." % name,
                          {name: "must be true or false"})
