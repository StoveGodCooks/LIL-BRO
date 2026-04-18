"""Tests for tool-call extraction regex — both Qwen and Llama formats."""

from __future__ import annotations


from src_local.agents.ollama_agent import _extract_text_tool_calls


class TestQwenFormat:
    """Standard format: {"name": "tool", "arguments": {...}}"""

    def test_basic_tool_call(self):
        text = 'Let me read that file. {"name": "read_file", "arguments": {"path": "main.py"}}'
        calls, cleaned = _extract_text_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["function"]["name"] == "read_file"
        assert calls[0]["function"]["arguments"]["path"] == "main.py"
        assert "read_file" not in cleaned

    def test_multiple_tool_calls(self):
        text = (
            '{"name": "read_file", "arguments": {"path": "a.py"}} '
            'and then {"name": "read_file", "arguments": {"path": "b.py"}}'
        )
        calls, cleaned = _extract_text_tool_calls(text)
        assert len(calls) == 2

    def test_nested_arguments(self):
        text = '{"name": "edit_file", "arguments": {"path": "x.py", "old_string": "a", "new_string": "b"}}'
        calls, _ = _extract_text_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["function"]["arguments"]["old_string"] == "a"

    def test_code_fence_stripped(self):
        text = "Here's the fix:\n```json\n{\"name\": \"write_file\", \"arguments\": {\"path\": \"x.py\", \"content\": \"hi\"}}\n```"
        calls, cleaned = _extract_text_tool_calls(text)
        assert len(calls) == 1
        assert "```" not in cleaned

    def test_no_tool_calls(self):
        text = "I don't need any tools for this. Just some regular text."
        calls, cleaned = _extract_text_tool_calls(text)
        assert len(calls) == 0
        assert cleaned == text.strip()


class TestLlamaFormat:
    """Llama 3.1+ format: {"type": "function", "function": {"name": ..., "arguments": ...}}"""

    def test_llama_tool_call(self):
        text = '{"type": "function", "function": {"name": "read_file", "arguments": {"path": "main.py"}}}'
        calls, cleaned = _extract_text_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["function"]["name"] == "read_file"
        assert calls[0]["function"]["arguments"]["path"] == "main.py"

    def test_llama_with_surrounding_text(self):
        text = 'I\'ll read the file now. {"type": "function", "function": {"name": "list_directory", "arguments": {"path": "."}}} Let me check.'
        calls, cleaned = _extract_text_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["function"]["name"] == "list_directory"
        assert "list_directory" not in cleaned

    def test_llama_in_code_fence(self):
        text = '```json\n{"type": "function", "function": {"name": "grep_files", "arguments": {"pattern": "TODO", "path": "."}}}\n```'
        calls, cleaned = _extract_text_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["function"]["name"] == "grep_files"


class TestMixedFormats:
    """Both formats can appear in the same response."""

    def test_mixed_formats(self):
        text = (
            '{"type": "function", "function": {"name": "read_file", "arguments": {"path": "a.py"}}} '
            '{"name": "write_file", "arguments": {"path": "b.py", "content": "x"}}'
        )
        calls, _ = _extract_text_tool_calls(text)
        assert len(calls) == 2
        names = {c["function"]["name"] for c in calls}
        assert "read_file" in names
        assert "write_file" in names


class TestEdgeCases:
    """Malformed input shouldn't crash."""

    def test_invalid_json_args(self):
        text = '{"name": "read_file", "arguments": {invalid json}}'
        calls, _ = _extract_text_tool_calls(text)
        # Should gracefully skip, not crash.
        assert len(calls) == 0

    def test_empty_string(self):
        calls, cleaned = _extract_text_tool_calls("")
        assert len(calls) == 0
        assert cleaned == ""

    def test_partial_json(self):
        text = '{"name": "read_file", "argu'
        calls, _ = _extract_text_tool_calls(text)
        assert len(calls) == 0
