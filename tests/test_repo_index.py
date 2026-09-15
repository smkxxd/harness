from pathlib import Path

from pico.repo_index import RepoIndex
from pico.tool_context import ToolContext
from pico.tools import build_tool_registry


def test_repo_index_finds_python_and_java_symbols(tmp_path):
    (tmp_path / "auth.py").write_text(
        "class TokenService:\n"
        "    def validate_token(self, token):\n"
        "        return bool(token)\n",
        encoding="utf-8",
    )
    java_dir = tmp_path / "src"
    java_dir.mkdir()
    (java_dir / "AuthController.java").write_text(
        "package demo;\n"
        "public class AuthController {\n"
        "  public boolean login(String token) { return token != null; }\n"
        "}\n",
        encoding="utf-8",
    )

    index = RepoIndex(tmp_path)

    results = index.search("validate token")
    symbol_context = index.symbol_context("AuthController")

    assert results[0]["path"] == "auth.py"
    assert any(symbol["name"] == "validate_token" for symbol in results[0]["symbols"])
    assert symbol_context[0]["path"] == "src/AuthController.java"
    assert "class AuthController" in symbol_context[0]["content"]


def test_repo_index_refresh_reuses_unchanged_entries_and_updates_changed_files(tmp_path):
    source = tmp_path / "service.py"
    source.write_text("def old_name():\n    return 1\n", encoding="utf-8")
    index = RepoIndex(tmp_path)

    index.refresh()
    first_parsed_count = index.parsed_file_count
    index.refresh()

    assert index.parsed_file_count == first_parsed_count

    source.write_text("def replacement_name():\n    return 200\n", encoding="utf-8")
    results = index.search("replacement_name")

    assert index.parsed_file_count == first_parsed_count + 1
    assert results[0]["path"] == "service.py"


def test_repo_search_tools_share_runtime_index(tmp_path):
    (tmp_path / "payments.py").write_text(
        "class PaymentService:\n"
        "    def refund(self, order_id):\n"
        "        return order_id\n",
        encoding="utf-8",
    )
    index = RepoIndex(tmp_path)
    context = ToolContext(
        root=tmp_path,
        path_resolver=lambda raw_path: (tmp_path / raw_path).resolve(),
        shell_env_provider=lambda: {"PWD": str(tmp_path)},
        depth=1,
        max_depth=1,
        spawn_delegate=lambda args: "unused",
        repo_index=index,
    )
    tools = build_tool_registry(context)

    search_result = tools["search_repo"]["run"]({"query": "payment refund", "top_k": 3})
    symbol_result = tools["get_symbol"]["run"]({"symbol": "PaymentService"})

    assert "payments.py" in search_result
    assert "PaymentService" in search_result
    assert '"symbol": "PaymentService"' in symbol_result
    assert index.refresh_count == 2


def test_repo_index_ignores_agent_state_directories(tmp_path):
    (tmp_path / "visible.py").write_text("def visible_symbol():\n    pass\n", encoding="utf-8")
    hidden = tmp_path / ".forgetrace"
    hidden.mkdir()
    (hidden / "secret.py").write_text("def hidden_symbol():\n    pass\n", encoding="utf-8")

    index = RepoIndex(tmp_path).refresh()

    assert "visible.py" in index.entries
    assert ".forgetrace/secret.py" not in index.entries
