"""MCP 도구는 사용자 문장이 아닌 모델의 도구 계약으로 전달한다."""

from backend.mcp_client.workflow import model_messages, native_tools


def test_catalog_is_not_in_user_messages():
    available = [({"id": "private-connection", "version": 1}, {
        "name": "search_private", "description": "검색", "schema": {"type": "object"}, "schema_hash": "abc",
    })]
    messages = model_messages([], available, [], allow_tools=True)
    assert all("private-connection" not in message["content"] for message in messages)
    assert all("search_private" not in message["content"] for message in messages)


def test_tools_have_stable_distinct_names_and_unmodified_schemas():
    schema = {"type": "object", "properties": {"limit": {"type": "integer", "default": 3}}}
    tool = {"name": "search", "description": "검색", "schema": schema, "schema_hash": "abc"}
    first = ({"id": "c1", "version": 1}, tool)
    second = ({"id": "c2", "version": 1}, tool)
    definitions, mapping = native_tools([first, second])
    assert definitions == native_tools([first, second])[0]
    assert len(mapping) == 2
    assert definitions[0]["function"]["strict"] is False
    assert definitions[0]["function"]["parameters"] == schema
    assert definitions[0]["function"]["name"] != definitions[1]["function"]["name"]
    changed = native_tools([({"id": "c1", "version": 2}, tool)])[0][0]["function"]["name"]
    assert changed != definitions[0]["function"]["name"]


def test_legacy_results_remain_data_without_inventing_tool_ids():
    messages = model_messages([], [], [{"status": "ok", "text": "기존 결과"}], allow_tools=False)
    assert any("기존 결과" in message["content"] for message in messages)
    assert all(message["role"] != "tool" for message in messages)
