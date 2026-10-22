import json

import pytest
from pydantic import ValidationError

from etsy_listings.core.preparation.distribution.src.marigold_worker.protocol import (
    REPLY,
    REQUEST,
    Acknowledged,
    Failure,
    HelloReply,
    InferenceResult,
    InferRequest,
    Progress,
    describe,
    encode,
)

from tests.support.marigold import capabilities_document, metadata_document


def v1_line(**message):
    """Exactly how a 1.0.0 worker serialised replies, before the schema existed."""
    return json.dumps(dict(protocol=1, **message)) + chr(10)


def test_replies_from_an_installed_1_0_0_worker_still_parse():
    checksum = "ab" * 32
    replies = [
        REPLY.validate_json(line)
        for line in (
            v1_line(type="hello", request_id="h", **capabilities_document()),
            v1_line(type="progress", request_id="i", step="depth"),
            v1_line(
                type="result",
                request_id="i",
                artifact="crops/depth.npz",
                checksum=checksum,
                cancelled=False,
                metadata=metadata_document("depth"),
            ),
            v1_line(type="result", request_id="c", acknowledged=True),
            v1_line(type="error", request_id="invalid", code="invalid_request", message="no"),
        )
    ]
    assert [type(reply) for reply in replies] == [
        HelloReply,
        Progress,
        InferenceResult,
        Acknowledged,
        Failure,
    ]
    assert replies[2].metadata.settings.ensemble_size == 3


def test_requests_round_trip_through_their_encoded_line():
    request = InferRequest.model_validate(
        {
            "request_id": "job-crop-depth",
            "role": "depth",
            "input": "work/crop.png",
            "output": "work/depth.npz",
            "settings": {"num_inference_steps": 4, "ensemble_size": 1},
        }
    )
    assert REQUEST.validate_json(encode(request)) == request


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"input": "../outside.png"}, "Unsafe relative cache path"),
        ({"input": "C:/outside.png"}, "Expected a relative cache path"),
        ({"output": "work/depth.png"}, "must name a .npz file"),
        ({"role": "albedo"}, "role"),
        ({"settings": {"num_inference_steps": 11, "ensemble_size": 3}}, "num_inference_steps"),
        # Booleans are integers to Python; the engine accepts only real counts.
        ({"settings": {"num_inference_steps": True, "ensemble_size": 3}}, "num_inference_steps"),
        ({"settings": {"num_inference_steps": 10}}, None),
        ({"priority": "high"}, "priority"),
        ({"type": "train"}, "type"),
        ({"protocol": 2}, "protocol"),
    ],
)
def test_requests_outside_the_contract_are_refused_with_a_short_reason(change, reason):
    message = {
        "protocol": 1,
        "type": "infer",
        "request_id": "r",
        "role": "depth",
        "input": "crop.png",
        "output": "depth.npz",
        "settings": {"num_inference_steps": 10, "ensemble_size": 3},
        **change,
    }
    with pytest.raises(ValidationError) as refused:
        REQUEST.validate_python(message)
    assert chr(10) not in describe(refused.value)
    if reason:
        assert reason in describe(refused.value)


def test_reply_missing_a_declared_field_is_malformed():
    document = capabilities_document()
    del document["installed_packages"]
    with pytest.raises(ValidationError, match="installed_packages"):
        REPLY.validate_json(v1_line(type="hello", request_id="h", **document))
