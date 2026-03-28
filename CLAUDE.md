# ops-code

## Coding Guidelines

1. **Simple is better than complicated.** This is a core principle. When in doubt, choose the simpler approach.
2. **Clean architecture with clearly identified inputs and outputs.** Every module must have an obvious entry point, a clear input, and a clear output. No hidden state, no surprise side effects.
3. **Small parts that do one specific thing.** Prefer many small, focused functions/files over one large file that does everything. Each piece should be independently understandable.
4. **If the code seems too complicated, it probably is.** Stop, step back, and find a simpler solution before continuing.
5. **Types are mandatory.** In TypeScript, `any` is forbidden — every variable, parameter, and return value must be explicitly typed. In Python, type hints must be used consistently. The JSON schema shared between Python and TypeScript must have matching type definitions on both sides.
6. **Names should be as short as possible without losing clarity.** Avoid redundant prefixes or suffixes that repeat context already implied by the module or file name. For example, prefer `watch()` in `watcher.ts` over `watchFile()`, or `Panel` in `panel.ts` over `ModelViewerPanel`. Private functions and methods can be particularly terse since their scope is limited.

---

## Project Structure

### Top-Level Layout

```
ops-code/
├── src/                    # VS Code extension (TypeScript)
├── python/                 # Python backend for model execution
├── media/                  # Web UI (HTML + TypeScript)
├── examples/               # Example OpenSees scripts
├── dist/                   # Compiled extension (generated)
├── esbuild.js              # Build config
├── tsconfig.json           # TypeScript config
└── package.json            # Extension manifest + dependencies
```

### `src/` — VS Code Extension (TypeScript)

The extension runs inside VS Code. It registers commands, manages the webview panel, and orchestrates Python execution.

**Files:**
- **`extension.ts`** — Entry point. Registers `ops-code.run` and `ops-code.screenshot` commands.
- **`panel.ts`** — Singleton webview panel. Manages the 3D viewer UI, loads model data, handles screenshots.
- **`runner.ts`** — Spawns Python subprocesses (`runner.py`, `analysis_runner.py`). Returns parsed JSON.
- **`watcher.ts`** — File system watcher. Debounces changes and reloads model on file save.
- **`types.ts`** — Shared TypeScript interfaces: `Node`, `Element`, `Support`, `NodalLoad`, `ModelData`, `AnalysisData`, message types.

**Data Flow (Load Model):**
```
User runs command
  → extension.ts: activate() registers commands
  → Panel.open() creates webview
  → panel.ts: load() calls runner.pythonPath() + runner.intercept()
  → runner.ts spawns python/runner.py
  → python/runner.py executes user script with interceptor
  → returns JSON to stdout
  → panel.ts posts { type: 'modelData', data } to webview
  → media/viewer.ts renders 3D scene
```

### `python/` — Model Execution & Data Capture

Python scripts execute user's OpenSees models and extract geometry/loads/analysis results.

**Files:**
- **`runner.py`** — Entry point. Injects `interceptor.py`, executes user script, prints JSON to stdout. Called for model loading only.
- **`analysis_runner.py`** — Similar to `runner.py`, but executes real OpenSees analysis (with `openseespy`). Wraps `ops.node()`, `ops.element()`, etc. to record model and results.
- **`interceptor.py`** — Patches OpenSees functions to intercept node/element/support/load definitions. Builds `ModelData` dict without running analysis.

**Key Pattern:**
Both runners compile user code and `exec()` it in an isolated namespace. They silence stdout (to preserve JSON output) and catch exceptions. Each runner emits JSON to stdout; `runner.ts` parses it.

### `media/` — Web UI (HTML + TypeScript)

Runs inside the webview (isolated from VS Code). Renders 3D model with Three.js and handles user interactions.

**Files:**
- **`viewer.html`** — HTML template. Defines canvas, toolbar, status bar. Includes CSP nonce for security.
- **`viewer.ts`** — Three.js application. Builds 3D geometry, renders forces/displacements, handles camera/mouse input. Sends messages back to extension (`type: 'screenshot'`, `type: 'runAnalysis'`).

**Message Flow (Webview ↔ Extension):**
```
Extension → Webview:
  { type: 'modelData', data }
  { type: 'analysisData', data, ndf }
  { type: 'loading' | 'analysisRunning' | 'error' }
  { type: 'takeScreenshot' }

Webview → Extension:
  { type: 'ready' }
  { type: 'runAnalysis' }
  { type: 'screenshot', data }
```

### `examples/` — Test Scripts

Sample OpenSees models for development and testing.

- **`cantilever.py`** — Simple 2D cantilever beam.
- **`pylone.py`** — More complex structure (pylon-like).

### Build & Output

- **`esbuild.js`** — Bundles `src/extension.ts` (and transitively all imports) into `dist/extension.js`.
- **`dist/extension.js`** — The compiled, bundled extension. VS Code loads this at runtime.
- **`tsconfig.json`** — Compiles all TypeScript files (both `src/` and `media/`) before esbuild bundles.

### Design Principles Applied

1. **Clear input/output:** Each module has a well-defined role (extension logic, Python execution, UI rendering).
2. **No hidden state:** File watching is explicit in `watcher.ts`. Python subprocess lifecycle is explicit in `runner.ts`.
3. **Separate concerns:** UI logic (viewer), extension logic (panel), and data transformation (runner/interceptor) are in different directories.
4. **Types at boundaries:** `types.ts` is the contract between TypeScript and Python. JSON schema must match on both sides.
