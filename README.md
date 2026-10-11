# Live Node Graph Engine

A take-home implementation of the Live Circuit Simulator task. The UI is React + React Flow, the API is Node/Express, persistence is MongoDB, and only the Python/FastAPI service invokes `ngspice -b`.

## Run

```bash
docker compose up --build
```

Open http://localhost:5173.

## Architecture

```text
React + React Flow
       |
       | graph JSON / save / load / simulate
       v
Node.js + Express  -----> MongoDB
       |
       | POST /simulate
       v
Python + FastAPI -----> ngspice -b
       |
       +---- result/errors ----> Node API ----> React canvas
```

## Graph -> netlist

Each React Flow handle gets a stable logical net name. A disjoint-set pass merges the output/input handles joined by wires, so every connected wire becomes one ngspice net. Number/Add/Multiply/Divide become the exact element forms required by the brief; Display contributes no element. The service appends `.op` and `.end`, runs ngspice in batch mode, and parses the operating-point node voltages.

Cycles and missing required inputs are rejected before ngspice. A topological pass also gives the dependency order used for error propagation. Each response carries the request id/version so the frontend can ignore late responses.

## Step 5

- **Fast edits:** the frontend debounces graph changes and aborts the previous HTTP request. It also increments a request sequence and applies only the newest response, preventing stale values after out-of-order responses.
- **Errors on the right node:** required-input and cycle checks happen before simulation. Runtime errors are returned with a node id; downstream nodes become `blocked` rather than retaining an old value.
- **ngspice trouble:** the simulator uses a subprocess timeout. The API returns a service error without crashing the rest of the app; the next graph edit automatically retries.
- **Untrusted formulas:** Formula text must match a strict allow-list containing only numbers, `a`, `b`, `+ - * /`, whitespace and parentheses/brackets. It is validated again server-side before substitution, so control lines such as `.control` never reach ngspice.

**Known limitation:** a deliberately malicious but syntactically valid arithmetic expression can still be computationally expensive; the current guard focuses on the task's shell/control-line injection case and the subprocess timeout limits execution time.

## Tests

```bash
cd simulator
pip install -r requirements.txt
pytest -q ../tests
```

The tests cover acceptance-style execution, loop detection, and unsafe Formula rejection. They use the same validation/netlist builder as the FastAPI service.

## AI usage note

AI assistance was used to scaffold the repository, review edge cases, and draft tests/documentation. The implementation should be understood and modified by the candidate during the live session.

## What I'd do next

- Add undo/redo and graph version history.
- Add a Subtract node during the live extension exercise.
- Add persistent named graphs and authentication if this became a multi-user product.

## Reverse proxy and troubleshooting

The Nginx frontend must forward `/api/*` to Express (`api:3000`). This is
configured in `frontend/nginx.conf`, copied into the image by the frontend
Dockerfile. Without the proxy, Nginx serves `index.html` in response to a
simulation request, and the browser reports `Unexpected token '<' ... not valid JSON`.

After updating or extracting this project, **rebuild** the images:

```bash
docker compose down
docker compose up --build -d
docker compose ps
```

Check that `http://localhost:3000/health` returns `{ "ok": true }`, then
refresh `http://localhost:5173` with Ctrl+Shift+R. The normal graph response is
JSON from `POST http://localhost:5173/api/simulate`, not HTML.
