"""여러 테스트에서 공유하는 검증용 도우미."""



def response(status="completed", content=None):
    return {
        "id": "resp_test",
        "object": "response",
        "created_at": 1,
        "model": "gpt-6-luna",
        "status": status,
        "output": [
            {
                "type": "message",
                "id": "msg_test",
                "role": "assistant",
                "status": "completed",
                "content": content
                if content is not None
                else [{"type": "output_text", "text": "Result", "annotations": []}],
            }
        ],
        "usage": {
            "input_tokens": 20,
            "output_tokens": 3,
            "total_tokens": 23,
            "input_tokens_details": {"cached_tokens": 10},
        },
    }
