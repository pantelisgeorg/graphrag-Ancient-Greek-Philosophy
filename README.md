# GraphRAG GUI

A PySide6 desktop wrapper for [Microsoft GraphRAG](https://microsoft.github.io/graphrag/)
that turns the CLI workflow into a single window: configure model providers, run indexing,
ask global / local / drift / basic queries, browse the parquet outputs, and visualize the
knowledge graph (inline Cytoscape.js view + one-click push to Neo4j).

Works with **OpenAI**, **Ollama**, and **LM Studio** (any OpenAI-compatible endpoint).

---

## Features

- **Project picker** — switch between multiple GraphRAG project roots; recents auto-saved.
- **Provider profiles** — saved presets for OpenAI / Ollama / LM Studio; "Apply" patches the
  active project's `settings.yaml` (with comment-preserving YAML round-trip).
- **Indexing tab** — runs `graphrag init / index / prompt-tune` via subprocess with **live
  log tailing**, milestone-based progress bar, and a **Clear / Reset** action with checkboxes
  for `output/`, `cache/`, `logs/` (so you can wipe before re-indexing new documents).
- **Query tab** — global / local / drift / basic search with **token-by-token streaming**
  using `graphrag.api.*_streaming`, plus a sources tree showing which entities and chunks
  the engine used, copy-to-clipboard, and save-transcript-as-markdown.
- **Data tab** — six parquet browsers (entities, relationships, communities,
  community_reports, text_units, documents) with text filter, full-cell inspector, CSV
  export.
- **Graph tab** — interactive Cytoscape.js view with community color, layout switcher
  (fcose / concentric / circle / breadthfirst / grid), min-degree slider, community
  toggles, search-to-highlight, and a side panel that lists neighbors of the selected
  node. Plus **Open in Neo4j** which pushes the extracted entities + relationships into
  a running Neo4j DBMS and opens Neo4j Browser for graph exploration.
- **Prompts tab** — edit any prompt in `prompts/` directly.
- **PDF → TXT helper** — standalone PySide6 window for batch-converting PDFs (with
  cleanup options: page range, hyphen-break join, repeated-header removal, paragraph
  rewrap) into GraphRAG-ready `.txt` files. Defaults to writing into the active project's
  `input/` folder.

---

## Requirements

- Python 3.12 or later
- [uv](https://docs.astral.sh/uv/) for dependency management
- Linux: `libxcb-cursor0` (Qt 6.5+ requirement)
  ```bash
  sudo apt install libxcb-cursor0
  ```
- Optional: [Neo4j](https://neo4j.com/) (Desktop or Community Server) for the "Open in Neo4j" button
- Optional: [Ollama](https://ollama.com/) or [LM Studio](https://lmstudio.ai/) for local models

---

## Neo4j setup (optional)

To use the **Open in Neo4j** button, add these to the project's `.env` file
(e.g. `ragtest/.env`):

```bash
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=neo4jragpass
```

You can create it in the app via **Project** tab → `.env` editor → **Save .env**, or by
hand. `.env` is git-ignored, so your credentials stay local. (The same `.env` also holds
`OPENAI_API_KEY` / `GRAPHRAG_API_KEY` for your models.)

---

## Quick start

```bash
git clone <your-fork-url> graphrag
cd graphrag

uv venv
uv sync

# 1. Set your OpenAI key (or skip if you'll use only local models)
export OPENAI_API_KEY=sk-...

# 2. Launch
./run.sh
```

First time? Open the bundled `ragtest/` project (it's pre-loaded as the first recent
project). Drop your `.txt` / `.csv` / `.json` files into `ragtest/input/`, then switch
to the **Index** tab and click **Run indexing**. Watch the log stream; when it finishes,
switch to the **Query** tab and ask a question.

---

## Workflows

### Index a new corpus
1. Drop `.txt` / `.csv` / `.json` files into the project's `input/` folder.
   - For PDFs: **Project** tab → **Open PDF → TXT helper**, add your PDFs, click Convert.
2. **Providers** tab → pick a profile → **Apply to project**.
3. **Index** tab → **Run indexing**.

### Re-index after changing input or prompts
1. **Index** tab → **Clear / Reset…**, check at least `output/`, click OK.
2. **Run indexing** again.

### Tune prompts for your domain or language
1. **Index** tab → fill **Domain** (e.g. `medical research papers on diabetes`),
   **Language** (e.g. `English` or `Greek`), keep `Chunk limit: 15`.
2. Click **Prompt-tune** — wait (it makes several LLM calls).
3. **Prompts** tab → verify `extract_graph.txt` shows your domain's entity types and
   examples in the right language.
4. Clear and re-index.

### Switch to local models (Ollama)
1. Pull the models you want, e.g. `ollama pull qwen2.5:14b && ollama pull nomic-embed-text-v2-moe`.
2. **Providers** tab → select the Ollama profile → set `Completion model` and
   `Embedding model` to match what you pulled → **Save changes** → **Apply to project**.
3. (Optional but recommended for GraphRAG) bake a 32k context into your model:
   ```bash
   cat > /tmp/Modelfile <<'EOF'
   FROM qwen2.5:14b
   PARAMETER num_ctx 32768
   EOF
   ollama create qwen2.5-14b-32k -f /tmp/Modelfile
   ```
   Then use `qwen2.5-14b-32k` as the completion model.

### Multilingual / Greek
- The bundled `greek prompts/` set is tuned for **Ancient Greek Philosophy** corpora (the
  sample `ragtest/` project ships pre-configured with it), and `english prompts/` holds the
  matching English set.
- It's easy to reconfigure for any other subject or language: run **Prompt-tune** with a
  different `Domain` / `Language`, or edit the prompts directly in the **Prompts** tab —
  the tuned files simply replace the defaults in the active project's `prompts/` folder.
- Run prompt-tune with `Language: Greek` (or your target language).
- Use a multilingual embedding model (`text-embedding-3-small` or `nomic-embed-text-v2-moe`).
- Bump `chunking.size` in `settings.yaml` to `1800–2000` to compensate for Greek's lower
  tokens-per-character compression with the `o200k_base` tokenizer.

---

## Project layout

```
graphrag/
├── app/                       Python package — all GUI + bridge code
│   ├── main.py                QApplication entry
│   ├── providers.py           Profile dataclass + settings.yaml patcher
│   ├── project.py             GraphRAGProject model + parquet readers + reset()
│   ├── indexer.py             QProcess wrapper for `graphrag init|index|prompt-tune`
│   ├── query_runner.py        Streaming query bridge (asyncio in a QThread)
│   ├── graph_viz.py           Cytoscape.js preview builder
│   ├── neo4j_loader.py        Pushes entities + relationships into Neo4j
│   ├── parquet_model.py       QAbstractTableModel over pandas DataFrame
│   ├── pdf_to_text.py         Standalone PDF → TXT helper
│   └── ui/                    One file per tab
├── ragtest/                   Bundled sample GraphRAG project
│   ├── settings.yaml
│   ├── prompts/
│   ├── input/                 (empty by default — add your own docs; git-ignored)
│   └── output/                (generated by indexing — git-ignored)
├── english prompts/           Ready-made English prompt set
├── greek prompts/             Ready-made Greek prompt set (Ancient Greek Philosophy)
├── run.sh                     Launcher for the main GUI
├── pdf2txt.sh                 Launcher for the PDF helper
└── pyproject.toml             uv-managed dependencies
```

App state lives under `~/.config/graphrag-gui/`:
- `providers.json` — saved profile definitions and the currently active one
- `recents.json` — list of recently opened project roots
- `history.jsonl` — append-only log of past queries and answers
- `js/` — cached Cytoscape.js bundle (downloaded once on first preview build)

---

## Tips and gotchas

- **Local models are slow on graph extraction.** A 27B model can take 30+ minutes to
  index a single paper. Use 7B–14B models (qwen2.5:14b is a good balance) for indexing,
  reserve larger models for query time.
- **Global / DRIFT answers are mediocre on tiny corpora.** They rely on rich community
  structure. With 1 document → 3 communities, there's almost nothing for them to reason
  over. Drop 5–10 related documents in and re-index for a fair test.
- **Context window matters.** GraphRAG's prompts are long. With Ollama, set
  `num_ctx >= 16384` (32k is safer) via a Modelfile or `OLLAMA_CONTEXT_LENGTH=32768`.
- **Ctrl+C** in the terminal that launched `./run.sh` closes the window cleanly.
- **Neo4j not reachable?** The "Open in Neo4j" button needs a running DBMS and
  `NEO4J_URI` / `NEO4J_USER` / `NEO4J_PASSWORD` in the project's `.env`.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `qt.qpa.plugin: Could not load the Qt platform plugin "xcb"` | `sudo apt install libxcb-cursor0` |
| `module 'graphrag' has no attribute …` | Run `uv sync` to refresh deps; this app targets graphrag 3.0+. |
| `RuntimeError: No entities.parquet found` in Query/Graph tab | You haven't indexed yet, or you ran Clear/Reset. Re-run **Index**. |
| Query streaming stops mid-answer | Context window too small for your local model. Increase `num_ctx`. |
| Indexing extraction is endless | Switch to a smaller / faster LLM, or use OpenAI for indexing. |
| Greek output has English entity types | Re-run **Prompt-tune** with `Language: Greek`, then clear and re-index. |
| PDF→TXT shows only first page | "Convert all pages" is unchecked. Re-check it and re-convert. |

---

## License

Released under the [MIT License](LICENSE). Copyright © 2026 George Pantelis.

Built on top of [Microsoft GraphRAG](https://github.com/microsoft/graphrag) (MIT),
[PySide6](https://www.qt.io/qt-for-python) (LGPL),
[pdfminer.six](https://github.com/pdfminer/pdfminer.six) (MIT),
and [Cytoscape.js](https://js.cytoscape.org/) (MIT).
