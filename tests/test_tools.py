"""Tests for tool execution — calculator safety, file sandboxing, permissions."""

from __future__ import annotations

from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Calculator (AST-based safe eval)
# ---------------------------------------------------------------------------

class TestCalculator:
    """The calculator tool uses AST parsing, not eval()."""

    def test_basic_arithmetic(self, tmp_project: Path):
        from src_local.agents.tools import _exec_calculate

        assert "= 7" in _exec_calculate({"expression": "3 + 4"}, tmp_project)
        assert "= 6" in _exec_calculate({"expression": "2 * 3"}, tmp_project)
        assert "= 2.5" in _exec_calculate({"expression": "5 / 2"}, tmp_project)
        assert "= 8" in _exec_calculate({"expression": "2 ** 3"}, tmp_project)

    def test_math_functions(self, tmp_project: Path):
        from src_local.agents.tools import _exec_calculate

        result = _exec_calculate({"expression": "sqrt(16)"}, tmp_project)
        assert "= 4" in result

        result = _exec_calculate({"expression": "abs(-5)"}, tmp_project)
        assert "= 5" in result

    def test_constants(self, tmp_project: Path):
        from src_local.agents.tools import _exec_calculate

        result = _exec_calculate({"expression": "pi"}, tmp_project)
        assert "3.14" in result

    def test_rejects_import(self, tmp_project: Path):
        from src_local.agents.tools import _exec_calculate

        result = _exec_calculate({"expression": "import os"}, tmp_project)
        assert "Error" in result

    def test_rejects_dunder(self, tmp_project: Path):
        from src_local.agents.tools import _exec_calculate

        result = _exec_calculate({"expression": "__import__('os')"}, tmp_project)
        assert "Error" in result

    def test_rejects_exec(self, tmp_project: Path):
        from src_local.agents.tools import _exec_calculate

        result = _exec_calculate({"expression": "exec('print(1)')"}, tmp_project)
        assert "Error" in result

    def test_rejects_open(self, tmp_project: Path):
        from src_local.agents.tools import _exec_calculate

        result = _exec_calculate({"expression": "open('/etc/passwd')"}, tmp_project)
        assert "Error" in result

    def test_rejects_attribute_access(self, tmp_project: Path):
        from src_local.agents.tools import _exec_calculate

        result = _exec_calculate({"expression": "().__class__.__bases__"}, tmp_project)
        assert "Error" in result

    def test_rejects_long_expression(self, tmp_project: Path):
        from src_local.agents.tools import _exec_calculate

        result = _exec_calculate({"expression": "1+" * 300}, tmp_project)
        assert "Error" in result

    def test_empty_expression(self, tmp_project: Path):
        from src_local.agents.tools import _exec_calculate

        result = _exec_calculate({"expression": ""}, tmp_project)
        assert "Error" in result


# ---------------------------------------------------------------------------
# File tool sandboxing
# ---------------------------------------------------------------------------

class TestFileSandbox:
    """File tools must not escape the project directory."""

    def test_read_file_inside_project(self, tmp_project: Path):
        from src_local.agents.tools import _exec_read_file

        result = _exec_read_file({"path": "main.py"}, tmp_project)
        assert "hello" in result

    def test_read_file_nested(self, tmp_project: Path):
        from src_local.agents.tools import _exec_read_file

        result = _exec_read_file({"path": "subdir/nested.txt"}, tmp_project)
        assert "nested" in result

    def test_read_file_path_traversal_blocked(self, tmp_project: Path):
        from src_local.agents.tools import _exec_read_file

        result = _exec_read_file({"path": "../../etc/passwd"}, tmp_project)
        assert "Error" in result or "outside" in result.lower() or "sandbox" in result.lower()

    def test_write_file_creates(self, tmp_project: Path):
        from src_local.agents.tools import _exec_write_file

        result = _exec_write_file(
            {"path": "new.py", "content": "x = 1\n"}, tmp_project
        )
        assert "Error" not in result
        assert (tmp_project / "new.py").read_text() == "x = 1\n"

    def test_write_file_path_traversal_blocked(self, tmp_project: Path):
        from src_local.agents.tools import _exec_write_file

        result = _exec_write_file(
            {"path": "../../evil.py", "content": "pwned"}, tmp_project
        )
        assert "Error" in result or "outside" in result.lower() or "sandbox" in result.lower()

    def test_edit_file(self, tmp_project: Path):
        from src_local.agents.tools import _exec_edit_file

        result = _exec_edit_file(
            {"path": "main.py", "old_string": "hello", "new_string": "world"},
            tmp_project,
        )
        assert "Error" not in result
        assert "world" in (tmp_project / "main.py").read_text()

    def test_edit_file_old_string_not_found(self, tmp_project: Path):
        from src_local.agents.tools import _exec_edit_file

        result = _exec_edit_file(
            {"path": "main.py", "old_string": "DOES_NOT_EXIST", "new_string": "x"},
            tmp_project,
        )
        assert "Error" in result or "not found" in result.lower()


# ---------------------------------------------------------------------------
# Permission model
# ---------------------------------------------------------------------------

class TestPermissions:
    """Write tools are blocked in read-only mode."""

    @staticmethod
    async def _exec_readonly(name: str, args: dict, project_dir: Path) -> str:
        from src_local.agents.tools import execute_tool

        return await execute_tool(name, args, project_dir=project_dir, write_access=False)

    @pytest.mark.asyncio
    async def test_write_blocked_when_readonly(self, tmp_project: Path):
        result = await self._exec_readonly("write_file", {"path": "x.py", "content": "x"}, tmp_project)
        assert "Error" in result
        assert "write access" in result.lower() or "read-only" in result.lower()

    @pytest.mark.asyncio
    async def test_edit_blocked_when_readonly(self, tmp_project: Path):
        result = await self._exec_readonly(
            "edit_file",
            {"path": "main.py", "old_string": "hello", "new_string": "x"},
            tmp_project,
        )
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_run_command_blocked_when_readonly(self, tmp_project: Path):
        result = await self._exec_readonly("run_command", {"command": "echo hi"}, tmp_project)
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_read_allowed_when_readonly(self, tmp_project: Path):
        result = await self._exec_readonly("read_file", {"path": "main.py"}, tmp_project)
        assert "hello" in result
