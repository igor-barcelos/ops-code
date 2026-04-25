"""Run one verification tool.

Reads `{"outputs": {...}}` JSON from stdin; loads the tool file given as argv[1];
calls `run(outputs)` once, where `outputs` matches the `Outputs` TS interface
(`{nodes: [...], elements: [...]}`). Prints whatever `run()` returns as JSON,
or `{"error": "..."}` if it raises.
"""
import argparse
import importlib.util
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tool_path")
    args = parser.parse_args()

    path = Path(args.tool_path)
    if not path.is_file():
        print(f"tool not found: {path}", file=sys.stderr)
        return 1

    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        print(f"failed to load {path}", file=sys.stderr)
        return 1
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    run = getattr(module, "run", None)
    if run is None:
        print(f"tool {path.name} has no run() function", file=sys.stderr)
        return 1

    outputs = json.loads(sys.stdin.read()).get("outputs", {})
    try:
        result = run(outputs)
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        return 0

    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
