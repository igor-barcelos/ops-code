"""Entry point: injects interceptor, executes user script, prints JSON to stdout."""

import ast
import io
import json
import os
import sys
from typing import Any

# Ensure this directory is on the path so interceptor can be imported
sys.path.insert(0, os.path.dirname(__file__))

from interceptor import InterceptorStop, ModelInterceptor, inject, restore


def _extract_tools(filepath: str) -> list[str]:
    try:
        with open(filepath, encoding='utf-8') as f:
            tree = ast.parse(f.read())
        tools: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == 'tools':
                tools.extend(alias.name for alias in node.names)
        return tools
    except Exception:
        return []


def run(script_path: str) -> dict[str, Any]:
    """Execute user script with interceptor active. Returns model data dict."""
    filepath = os.path.abspath(script_path)
    interceptor = ModelInterceptor()
    saved = inject(interceptor)
    error: str | None = None

    # Suppress user stdout so it does not corrupt our JSON output
    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    script_dir = os.path.dirname(filepath)
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)

    namespace: dict[str, Any] = {'__name__': '__main__', '__file__': filepath}
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            code = f.read()
        exec(compile(code, filepath, 'exec'), namespace)
    except InterceptorStop:
        pass
    except Exception as exc:
        error = str(exc)
    finally:
        sys.stdout = old_stdout
        restore(saved)

    # Read __viewer__ from script globals
    viewer = namespace.get('__viewer__')
    if isinstance(viewer, dict):
        interceptor.viewer = viewer

    result = interceptor.to_dict()
    result['error'] = error
    result['tools'] = _extract_tools(filepath)
    return result


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: runner.py <script_path>"}))
        sys.exit(1)
    print(json.dumps(run(sys.argv[1])))
