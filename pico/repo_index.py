"""Lightweight, code-aware repository index used by ForgeTrace.

The index deliberately stays dependency-free. It extracts symbols from Python
with ``ast`` and uses conservative patterns for Java/JavaScript/TypeScript.
It is refreshed incrementally inside a running agent: unchanged files keep
their parsed entries while changed and deleted files are updated.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
import re

from .workspace import IGNORED_PATH_NAMES


INDEXED_SUFFIXES = {
    ".c",
    ".cc",
    ".cpp",
    ".go",
    ".h",
    ".hpp",
    ".java",
    ".js",
    ".jsx",
    ".kt",
    ".kts",
    ".md",
    ".py",
    ".rs",
    ".tsx",
    ".ts",
}
MAX_INDEXED_FILE_BYTES = 1_000_000
MAX_SEARCH_RESULTS = 20
TOKEN_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[\u4e00-\u9fff]{2,}")
CAMEL_BOUNDARY_PATTERN = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")

LANGUAGE_BY_SUFFIX = {
    ".c": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".go": "go",
    ".h": "c",
    ".hpp": "cpp",
    ".java": "java",
    ".js": "javascript",
    ".jsx": "javascript",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".md": "markdown",
    ".py": "python",
    ".rs": "rust",
    ".ts": "typescript",
    ".tsx": "typescript",
}


@dataclass(frozen=True)
class Symbol:
    name: str
    kind: str
    line: int
    end_line: int


@dataclass
class IndexedFile:
    path: str
    language: str
    fingerprint: tuple[int, int]
    symbols: list[Symbol]
    imports: list[str]
    text: str
    lines: list[str]


def _tokens(text):
    expanded = CAMEL_BOUNDARY_PATTERN.sub(" ", str(text).replace("-", " ").replace(".", " "))
    return [match.group(0).lower() for match in TOKEN_PATTERN.finditer(expanded)]


def _python_symbols(text):
    symbols = []
    imports = []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return symbols, imports

    class SymbolVisitor(ast.NodeVisitor):
        def __init__(self):
            self.class_depth = 0

        def visit_ClassDef(self, node):
            symbols.append(
                Symbol(node.name, "class", int(node.lineno), int(getattr(node, "end_lineno", node.lineno)))
            )
            self.class_depth += 1
            self.generic_visit(node)
            self.class_depth -= 1

        def _visit_function(self, node):
            kind = "method" if self.class_depth else "function"
            symbols.append(
                Symbol(node.name, kind, int(node.lineno), int(getattr(node, "end_lineno", node.lineno)))
            )
            self.generic_visit(node)

        visit_FunctionDef = _visit_function
        visit_AsyncFunctionDef = _visit_function

        def visit_Import(self, node):
            imports.extend(alias.name for alias in node.names)

        def visit_ImportFrom(self, node):
            module = node.module or ""
            imports.append(module)
            imports.extend(f"{module}.{alias.name}".strip(".") for alias in node.names)

    SymbolVisitor().visit(tree)
    return sorted(symbols, key=lambda item: (item.line, item.name)), sorted(set(filter(None, imports)))


TYPE_PATTERN = re.compile(
    r"^\s*(?:(?:public|protected|private|abstract|final|sealed|static|export)\s+)*"
    r"(?P<kind>class|interface|enum|record|struct|trait)\s+(?P<name>[A-Za-z_$][\w$]*)"
)
FUNCTION_PATTERN = re.compile(
    r"^\s*(?:(?:public|protected|private|static|final|abstract|synchronized|async|export)\s+)*"
    r"(?:[\w$<>\[\],.?]+\s+)?(?P<name>[A-Za-z_$][\w$]*)\s*\([^;{}]*\)\s*(?:\{|=>)"
)
DECLARATION_PATTERN = re.compile(
    r"^\s*(?:def|func|fn|function)\s+(?P<name>[A-Za-z_$][\w$]*)\s*\("
)
IMPORT_PATTERN = re.compile(r"^\s*(?:import|from|use|package)\s+([^;]+)")
MARKDOWN_HEADING_PATTERN = re.compile(r"^\s{0,3}(?P<marks>#{1,6})\s+(?P<name>.+?)\s*$")


def _generic_symbols(text, language):
    symbols = []
    imports = []
    for number, line in enumerate(text.splitlines(), start=1):
        if language == "markdown":
            heading = MARKDOWN_HEADING_PATTERN.match(line)
            if heading:
                symbols.append(Symbol(heading.group("name").strip(), "heading", number, number))
            continue
        import_match = IMPORT_PATTERN.match(line)
        if import_match:
            imports.append(import_match.group(1).strip())
        type_match = TYPE_PATTERN.match(line)
        if type_match:
            symbols.append(Symbol(type_match.group("name"), type_match.group("kind"), number, number))
            continue
        declaration = DECLARATION_PATTERN.match(line)
        if declaration:
            symbols.append(Symbol(declaration.group("name"), "function", number, number))
            continue
        function_match = FUNCTION_PATTERN.match(line)
        if function_match:
            name = function_match.group("name")
            if name not in {"if", "for", "while", "switch", "catch"}:
                symbols.append(Symbol(name, "method", number, number))
    return symbols, sorted(set(imports))


class RepoIndex:
    """In-memory incremental index for one repository root."""

    def __init__(self, root):
        self.root = Path(root).resolve()
        self.entries: dict[str, IndexedFile] = {}
        self.refresh_count = 0
        self.parsed_file_count = 0

    def _iter_files(self):
        for path in self.root.rglob("*"):
            try:
                relative = path.relative_to(self.root)
            except ValueError:
                continue
            if any(part in IGNORED_PATH_NAMES or part == ".forgetrace" for part in relative.parts):
                continue
            if not path.is_file() or path.suffix.lower() not in INDEXED_SUFFIXES:
                continue
            try:
                if path.stat().st_size > MAX_INDEXED_FILE_BYTES:
                    continue
            except OSError:
                continue
            yield path, relative.as_posix()

    def _parse_file(self, path, relative, fingerprint):
        text = path.read_text(encoding="utf-8", errors="replace")
        language = LANGUAGE_BY_SUFFIX.get(path.suffix.lower(), "text")
        if language == "python":
            symbols, imports = _python_symbols(text)
        else:
            symbols, imports = _generic_symbols(text, language)
        self.parsed_file_count += 1
        return IndexedFile(
            path=relative,
            language=language,
            fingerprint=fingerprint,
            symbols=symbols,
            imports=imports,
            text=text,
            lines=text.splitlines(),
        )

    def refresh(self):
        seen = set()
        for path, relative in self._iter_files():
            seen.add(relative)
            try:
                stat = path.stat()
                fingerprint = (int(stat.st_mtime_ns), int(stat.st_size))
            except OSError:
                continue
            current = self.entries.get(relative)
            if current is not None and current.fingerprint == fingerprint:
                continue
            self.entries[relative] = self._parse_file(path, relative, fingerprint)
        for relative in set(self.entries) - seen:
            del self.entries[relative]
        self.refresh_count += 1
        return self

    @staticmethod
    def _path_matches(path, path_filter):
        normalized = str(path_filter or ".").replace("\\", "/").strip("/")
        return not normalized or normalized == "." or path == normalized or path.startswith(normalized + "/")

    @staticmethod
    def _entry_score(entry, query, terms):
        path_lower = entry.path.lower()
        symbol_names = [symbol.name.lower() for symbol in entry.symbols]
        symbol_token_set = set(_tokens(" ".join(symbol.name for symbol in entry.symbols)))
        import_text = " ".join(entry.imports).lower()
        content_lower = entry.text.lower()
        score = 0.0
        reasons = []

        if query in symbol_names:
            score += 20
            reasons.append("exact symbol")
        if query and query in path_lower:
            score += 9
            reasons.append("path")
        if query and query in content_lower:
            score += 4
            reasons.append("exact text")

        for term in terms:
            if term in symbol_token_set:
                score += 7
                reasons.append(f"symbol:{term}")
            if term in _tokens(path_lower):
                score += 4
                reasons.append(f"path:{term}")
            if term in import_text:
                score += 2
                reasons.append(f"import:{term}")
            score += min(content_lower.count(term), 3)
        return score, list(dict.fromkeys(reasons))

    @staticmethod
    def _best_line(entry, terms):
        best_number = 1
        best_score = -1
        for number, line in enumerate(entry.lines, start=1):
            lowered = line.lower()
            score = sum(1 for term in terms if term in lowered)
            if score > best_score:
                best_number = number
                best_score = score
        start = max(1, best_number - 1)
        end = min(len(entry.lines), best_number + 1)
        snippet = " ".join(line.strip() for line in entry.lines[start - 1:end] if line.strip())
        return best_number, snippet[:240]

    def search(self, query, path_filter=".", language="", top_k=8):
        self.refresh()
        normalized_query = str(query).strip().lower()
        terms = list(dict.fromkeys(_tokens(normalized_query)))
        if not terms:
            return []
        language = str(language or "").strip().lower()
        ranked = []
        for entry in self.entries.values():
            if language and entry.language != language:
                continue
            if not self._path_matches(entry.path, path_filter):
                continue
            score, reasons = self._entry_score(entry, normalized_query, terms)
            if score <= 0:
                continue
            line, snippet = self._best_line(entry, terms)
            matching_symbols = [
                {
                    "name": symbol.name,
                    "kind": symbol.kind,
                    "line": symbol.line,
                }
                for symbol in entry.symbols
                if any(term in symbol.name.lower() for term in terms)
            ][:6]
            ranked.append(
                {
                    "path": entry.path,
                    "language": entry.language,
                    "score": round(score, 2),
                    "line": line,
                    "symbols": matching_symbols,
                    "snippet": snippet,
                    "reasons": reasons[:5],
                }
            )
        ranked.sort(key=lambda item: (-item["score"], item["path"]))
        return ranked[: max(1, min(int(top_k), MAX_SEARCH_RESULTS))]

    def symbol_context(self, symbol_name, path_filter=".", context_lines=4):
        self.refresh()
        expected = str(symbol_name).strip().lower()
        results = []
        for entry in self.entries.values():
            if not self._path_matches(entry.path, path_filter):
                continue
            for symbol in entry.symbols:
                if symbol.name.lower() != expected:
                    continue
                start = max(1, symbol.line - int(context_lines))
                end = min(len(entry.lines), max(symbol.end_line, symbol.line) + int(context_lines))
                body = "\n".join(
                    f"{number:>4}: {entry.lines[number - 1]}"
                    for number in range(start, end + 1)
                )
                results.append(
                    {
                        "path": entry.path,
                        "language": entry.language,
                        "name": symbol.name,
                        "kind": symbol.kind,
                        "line": symbol.line,
                        "start": start,
                        "end": end,
                        "content": body,
                    }
                )
        return sorted(results, key=lambda item: (item["path"], item["line"]))
