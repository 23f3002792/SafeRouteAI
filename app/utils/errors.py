from flask import jsonify


def error_response(code: int, key: str, message: str, details: dict = None):
    """
    Return the standard error envelope defined in the API contract:

        {
            "error": {
                "code":    "MACHINE_KEY",
                "message": "human readable",
                "details": {}   # optional
            }
        }
    """
    body = {
        "error": {
            "code": key,
            "message": message,
            "details": details or {},
        }
    }
    return jsonify(body), code
