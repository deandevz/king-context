# Use Ollama with King Context

King Context can use Ollama for LLM-backed stages in `king-scrape` and
`king-research`. Use this guide when you want local model execution or a direct
Ollama Cloud/native host instead of OpenRouter.

Ollama provider support is beta. If you find bugs, or if you validate models
that chunk and enrich content with quality close to Gemini through OpenRouter,
open an issue with the model name, command, topic or URL, and a short quality
note: [King Context issues](https://github.com/deandevz/king-context/issues).

## Install Ollama

On macOS, install Ollama with one of these options:

```bash
brew install ollama
```

Or download the macOS app from the
[Ollama download page](https://ollama.com/download).

After installation, confirm that the CLI is available:

```bash
ollama --version
```

## Start Ollama

If you installed the macOS app, open Ollama once so the local server starts.
If you installed the CLI only, start the server in a terminal:

```bash
ollama serve
```

The local API runs at `http://localhost:11434`.

## Download a model

Download the model before running a King Context enrichment job:

```bash
ollama pull qwen2.5:7b
```

The first download can take several minutes, depending on the model size and
your network. After the model is downloaded, later runs load it from your local
Ollama model store.

For a faster smoke test, use a smaller model:

```bash
ollama pull qwen2.5:1.5b
```

List local models with:

```bash
ollama list
```

## Configure King Context for local Ollama

Set these variables in your project `.env` or `.king-context/.env`:

```dotenv
ENRICH_PROVIDER=ollama
ENRICH_MODEL=qwen2.5:7b
OLLAMA_API_MODE=openai
OLLAMA_BASE_URL=http://localhost:11434/v1
OLLAMA_API_KEY=
CONCURRENCY_OLLAMA=1
```

`OLLAMA_API_MODE=openai` uses Ollama's OpenAI-compatible API at
`/v1/chat/completions`. Start with `CONCURRENCY_OLLAMA=1` for local runs. Raise
it to `2` only after you confirm that your machine handles the workload well.

Optional: configure other LLM-backed stages too:

```dotenv
FILTER_PROVIDER=ollama
FILTER_MODEL=qwen2.5:7b
RESEARCH_PROVIDER=ollama
RESEARCH_MODEL=qwen2.5:7b
```

## Check the configuration

Run the LLM doctor:

```bash
kctx llm-doctor --json
```

If you are working from the repository without installed wrapper scripts, use:

```bash
python -m context_cli.cli llm-doctor --json
```

When an Ollama stage is configured, the output includes the API mode, base URL,
reachability, and whether the configured models are present.

## Run a small scrape

Use `--no-llm-filter` for the first test so only the enrichment stage exercises
Ollama:

```bash
king-scrape https://docs.example.com \
  --name ollama-smoke \
  --stop-after enrich \
  --yes \
  --no-llm-filter
```

The enrichment cost prompt should use local runtime wording instead of an
OpenRouter dollar estimate.

## Configure fallback to OpenRouter

Fallback is optional and one-way: Ollama to OpenRouter.

```dotenv
ENABLE_FALLBACK=true
FALLBACK_MODEL=google/gemini-3-flash-preview
OPENROUTER_API_KEY=...
```

Use fallback when you want the pipeline to continue if the local Ollama model is
unavailable, returns invalid JSON, or fails enrichment validation after retries.
Fallback may incur OpenRouter cost.

## Use Ollama Cloud or a native Ollama host

For direct Ollama Cloud/native API access, use native mode:

```dotenv
ENRICH_PROVIDER=ollama
ENRICH_MODEL=gpt-oss:120b
OLLAMA_API_MODE=native
OLLAMA_BASE_URL=https://ollama.com
OLLAMA_API_KEY=...
CONCURRENCY_OLLAMA=1
```

Native mode calls `/api/chat` with `stream: false` and JSON mode enabled.

## Help validate models

Different local models can vary in JSON reliability, chunk quality, and
enrichment quality. Contributions are useful when they include:

- The model name and tag, such as `qwen2.5:7b`.
- The King Context command and relevant provider environment variables.
- Whether the run completed chunking, enrichment, and indexing.
- A brief comparison against Gemini through OpenRouter when available.

Open model validation results or bugs in
[King Context issues](https://github.com/deandevz/king-context/issues).
