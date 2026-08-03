"""
ai_vertex.py — shared Gemini caller for the OFN backend AI agents.

Why this exists
---------------
Every agent (Thaiyme, Tarrigon, Lavendir/Website-AI, Provenance) used the
API-key Gemini *Developer API* (google.generativeai). That path is on the
low free-tier quota and throws "AI service rate limited" (HTTP 429) under load.

This module routes those calls through **Vertex AI** instead, which has far
higher quotas and authenticates with the Cloud Run runtime service account via
Application Default Credentials — no API key. It also wraps every call in
429/500/503 exponential-backoff retries.

Fallback
--------
Set env `GEMINI_USE_VERTEX=false` to fall back to the Developer API
(google.generativeai + GOOGLE_API_KEY) with no code change. The builder helpers
below emit the correct object types for whichever backend is active, so agent
code is identical either way.

Agent usage pattern
--------------------
    import ai_vertex as av
    tools = av.make_tools([{ "name":..., "description":..., "parameters": <openapi dict|None> }, ...])
    model = av.make_model("gemini-2.5-flash", system_instruction=sys,
                          generation_config={"temperature":0.4,"max_output_tokens":4096},
                          tools=tools)
    chat  = model.start_chat(history=av.make_history([("user", "hi"), ("model", "hello")]))
    resp  = av.send_message(chat, user_msg)                      # retry-wrapped
    ...
    resp  = av.send_message(chat, [av.function_response_part(name, payload_dict)])

Response parsing (resp.candidates[].content.parts[].function_call/.text) is
identical on Vertex and the Developer API, so existing loops are unchanged.
"""
import os
import time
import logging

logger = logging.getLogger(__name__)

_PROJECT = (os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCLOUD_PROJECT")
            or "animated-flare-421518")
_LOCATION = (os.getenv("GOOGLE_CLOUD_LOCATION") or os.getenv("VERTEX_REGION")
             or "us-central1")


def use_vertex() -> bool:
    return os.getenv("GEMINI_USE_VERTEX", "true").strip().lower() != "false"


_vertex_inited = False


def _ensure_vertex():
    global _vertex_inited
    if not _vertex_inited:
        import vertexai
        vertexai.init(project=_PROJECT, location=_LOCATION)
        _vertex_inited = True
        logger.info("[ai_vertex] Vertex AI initialized project=%s location=%s", _PROJECT, _LOCATION)


def _configure_dev():
    import google.generativeai as genai
    genai.configure(api_key=os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or "")


# ── Retry ────────────────────────────────────────────────────────────────────
def _is_retryable(exc) -> bool:
    code = getattr(exc, "code", None)
    try:
        if int(code) in (429, 500, 503):
            return True
    except (TypeError, ValueError):
        pass
    if type(exc).__name__ in (
        "ResourceExhausted", "ServiceUnavailable", "InternalServerError",
        "TooManyRequests", "DeadlineExceeded",
    ):
        return True
    s = str(exc).lower()
    return ("429" in s or "503" in s or "500" in s
            or "quota" in s or "exhausted" in s or "overloaded" in s or "unavailable" in s)


def with_retry(fn, *args, retries: int = 4, **kwargs):
    """Call fn(*args, **kwargs), retrying transient 429/500/503 with backoff."""
    attempt = 0
    while True:
        try:
            return fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001
            if attempt >= retries or not _is_retryable(e):
                raise
            delay = 0.6 * (2 ** attempt)
            logger.warning("[ai_vertex] transient error (attempt %d): %s — retrying in %.1fs",
                           attempt + 1, e, delay)
            time.sleep(delay)
            attempt += 1


def send_message(chat, message, retries: int = 4):
    return with_retry(chat.send_message, message, retries=retries)


def generate_content(model, content, retries: int = 4):
    return with_retry(model.generate_content, content, retries=retries)


# ── Model construction ───────────────────────────────────────────────────────
def make_model(model_name, system_instruction=None, generation_config=None, tools=None):
    if use_vertex():
        _ensure_vertex()
        from vertexai.generative_models import GenerativeModel
        kwargs = {}
        if system_instruction is not None:
            kwargs["system_instruction"] = system_instruction
        if generation_config is not None:
            kwargs["generation_config"] = generation_config
        if tools is not None:
            kwargs["tools"] = tools
        return GenerativeModel(model_name, **kwargs)

    _configure_dev()
    import google.generativeai as genai
    kwargs = {}
    if system_instruction is not None:
        kwargs["system_instruction"] = system_instruction
    if generation_config is not None:
        kwargs["generation_config"] = generation_config
    if tools is not None:
        kwargs["tools"] = tools
    return genai.GenerativeModel(model_name=model_name, **kwargs)


# ── Tools ────────────────────────────────────────────────────────────────────
def make_tools(fn_specs):
    """
    fn_specs: list of {"name": str, "description": str, "parameters": <OpenAPI dict>|None}
    Returns the tools list in the shape the active backend expects, or None.
    """
    fn_specs = [s for s in (fn_specs or []) if s and s.get("name")]
    if not fn_specs:
        return None

    if use_vertex():
        from vertexai.generative_models import Tool, FunctionDeclaration
        decls = []
        for s in fn_specs:
            # Vertex requires `parameters`; use an empty object schema for no-arg tools.
            params = s.get("parameters") or {"type": "object", "properties": {}}
            decls.append(FunctionDeclaration(
                name=s["name"], description=s.get("description", ""), parameters=params))
        return [Tool(function_declarations=decls)]

    # Developer API accepts the plain-dict shape.
    decls = []
    for s in fn_specs:
        d = {"name": s["name"], "description": s.get("description", "")}
        if s.get("parameters"):
            d["parameters"] = s["parameters"]
        decls.append(d)
    return [{"function_declarations": decls}]


# ── History & function-response parts ────────────────────────────────────────
def make_history(turns):
    """turns: list of (role, text) where role is 'user' or 'model'."""
    if use_vertex():
        from vertexai.generative_models import Content, Part
        out = []
        for role, text in turns:
            out.append(Content(role=role, parts=[Part.from_text(text or "")]))
        return out
    return [{"role": role, "parts": [{"text": text or ""}]} for role, text in turns]


def embed_query(text, model="text-embedding-004", task_type="RETRIEVAL_QUERY"):
    """Return the embedding vector (list[float]) for a retrieval query.

    Vertex needs no API key (uses ADC); the Developer-API fallback needs
    GOOGLE_API_KEY. Same underlying text-embedding-004 model either way, so
    vectors stay compatible with what sync_embeddings.py stored.
    """
    if use_vertex():
        _ensure_vertex()
        from vertexai.language_models import TextEmbeddingModel, TextEmbeddingInput
        emb_model = TextEmbeddingModel.from_pretrained(model)
        inp = TextEmbeddingInput(text=text, task_type=task_type)
        result = with_retry(emb_model.get_embeddings, [inp])
        return list(result[0].values)

    _configure_dev()
    import google.generativeai as genai
    dev_model = model if model.startswith("models/") else f"models/{model}"
    out = with_retry(genai.embed_content, model=dev_model, content=text,
                     task_type=task_type.lower())
    return out["embedding"]


def function_response_part(name, response):
    """Build a single function-response part for sending tool results back."""
    resp = response if isinstance(response, dict) else {"value": response}
    if use_vertex():
        from vertexai.generative_models import Part
        return Part.from_function_response(name=name, response=resp)
    return {"function_response": {"name": name, "response": resp}}
