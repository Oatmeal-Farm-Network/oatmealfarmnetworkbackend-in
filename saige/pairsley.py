"""
Pairsley (pronounced "Parsley") — the food-service AI agent for restaurateurs,
chefs, and professional kitchens on OFN.

Pairs with Saige (which serves farmers). Pairsley runs against the same OFN
marketplace data but is tuned for the buyer side of the table — recipe
costing, par levels, seasonal sourcing, provenance storytelling, and
restaurant account changes.

Architecture mirrors Saige's patterns (ReAct tool-call loop, Redis short-term
memory, Firestore long-term memory, Firestore vector-RAG) so frontends can
swap between the two with a different endpoint.

Long-term memory
----------------
All messages persist to the Firestore ``Pairsley_chats`` collection (same
schema as Saige's ``threads``, just a different root collection).

Short-term memory
-----------------
The last N messages of each thread are cached in Redis via the shared
``message_buffer`` module — same TTL, same structure as Saige so one Redis
backs both agents.

RAG
---
Pairsley's knowledge base lives in the Firestore ``Pairsley_chunks``
collection. Source docs originate from Firebase Storage at ``artemis/Parsley``
and are embedded into ``Pairsley_chunks`` by the sync job.
"""
from __future__ import annotations

import datetime
import logging
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.tools import tool

from chat_history import ChatHistory
from config import DB_CONFIG, SHORT_TERM_N
from llm import llm
from message_buffer import get_last_n, push_message
from rag import RAGSystem

try:
    import pymssql
    _PMS_AVAILABLE = True
except ImportError:
    _PMS_AVAILABLE = False

logger = logging.getLogger("pairsley")

# ---------------------------------------------------------------------------
# Firestore collections / storage paths
# ---------------------------------------------------------------------------

PAIRSLEY_CHATS_COLLECTION = "Pairsley_chats"
PAIRSLEY_CHUNKS_COLLECTION = "Pairsley_chunks"
PAIRSLEY_DOCS_PATH = "artemis/Parsley"


# ---------------------------------------------------------------------------
# Long-term memory: Firestore-backed chat history for Pairsley_chats
# ---------------------------------------------------------------------------

class PairsleyChatHistory(ChatHistory):
    """ChatHistory variant that stores conversations under the
    ``Pairsley_chats`` root collection instead of ``threads``."""

    @property
    def threads_col(self):
        try:
            db = self.firestore_db
            if db:
                return db.collection(PAIRSLEY_CHATS_COLLECTION)
        except Exception as e:
            logger.error("[Pairsley] threads_col error: %s", e)
        return None


pairsley_chat_history = PairsleyChatHistory()

# ---------------------------------------------------------------------------
# RAG over Pairsley_chunks
# ---------------------------------------------------------------------------

rag_pairsley = RAGSystem(PAIRSLEY_CHUNKS_COLLECTION, label="pairsley")


# ---------------------------------------------------------------------------
# DB helpers (for account-change tools)
# ---------------------------------------------------------------------------

def _connect():
    if not _PMS_AVAILABLE or not all([DB_CONFIG.get("host"), DB_CONFIG.get("user"), DB_CONFIG.get("database")]):
        return None
    try:
        return pymssql.connect(
            server=DB_CONFIG["host"], port=DB_CONFIG["port"],
            user=DB_CONFIG["user"], password=DB_CONFIG["password"],
            database=DB_CONFIG["database"], as_dict=True,
        )
    except Exception as e:
        logger.error("[Pairsley] DB connect failed: %s", e)
        return None


def _query(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    conn = _connect()
    if not conn:
        return []
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        return list(cur.fetchall())
    except Exception as e:
        logger.error("[Pairsley] query failed: %s", e)
        return []
    finally:
        conn.close()


def _execute(sql: str, params: tuple = ()) -> int:
    conn = _connect()
    if not conn:
        return 0
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()
        return cur.rowcount
    except Exception as e:
        logger.error("[Pairsley] execute failed: %s", e)
        return 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Tools specific to Pairsley
# ---------------------------------------------------------------------------

@tool
def pairsley_knowledge_tool(query: str = "") -> str:
    """Search Pairsley's curated food-service knowledge base (professional
    kitchen playbooks, HACCP guidance, menu engineering, food costing
    formulas, sourcing best practices) for a chef-facing question. Use
    when the user asks "how do I", "what's the right way to", "best
    practice for" about anything back-of-house — food safety, prep, menu
    writing, inventory process, sourcing ethics. Returns the most relevant
    passages from Pairsley's library."""
    q = (query or "").strip()
    if not q:
        return "Give me a specific question to look up."
    ctx = rag_pairsley.get_context_for_query(q)
    if not ctx:
        return "I couldn't find anything in my knowledge base for that."
    return ctx


@tool
def update_restaurant_profile_tool(
    business_name: str = "",
    description: str = "",
    slogan: str = "",
    website: str = "",
    business_id: int = 0,
) -> str:
    """Update the restaurant's public profile (name, description, slogan,
    website). Pass only the fields the chef wants to change — leave the
    rest blank and they'll stay as they are. business_id is injected from
    session state. Use when the chef says "update our tagline", "change
    the website on our OFN profile", "fix our description"."""
    if not business_id or int(business_id) <= 0:
        return "I need to know which restaurant this is for — open Pairsley from your restaurant dashboard."
    sets: List[str] = []
    params: List[Any] = []
    if business_name:
        sets.append("BusinessName = %s"); params.append(str(business_name)[:200])
    if description:
        sets.append("BusinessDescription = %s"); params.append(str(description)[:4000])
    if slogan:
        sets.append("BusinessSlogan = %s"); params.append(str(slogan)[:300])
    if website:
        sets.append("BusinessWebsite = %s"); params.append(str(website)[:500])
    if not sets:
        return "Tell me what to change — a new name, description, slogan, or website."
    params.append(int(business_id))
    sql = f"UPDATE Business SET {', '.join(sets)} WHERE BusinessID = %s"
    n = _execute(sql, tuple(params))
    if n == 0:
        return "I couldn't find that restaurant to update."
    return f"Updated your restaurant profile ({len(sets)} field(s))."


pairsley_own_tools = [
    pairsley_knowledge_tool,
    update_restaurant_profile_tool,
]


# ---------------------------------------------------------------------------
# Prompt — Pairsley's personality and tool contract
# ---------------------------------------------------------------------------

PAIRSLEY_SYSTEM_PROMPT = """You are Pairsley (pronounced "Parsley"), the food-service AI for chefs,
restaurateurs, and professional kitchen operators on Oatmeal Farm Network.

Voice:
- Friendly and warm, but professionally sharp — you talk like a trusted sous chef
  who also has an MBA. No fluff, no emoji, no corporate softening.
- You never pretend to know prices, farms, or inventory you haven't looked up.
  If a user asks about costs, menus, pars, or farm provenance, you call a tool
  first, then answer from the tool result.

Capabilities — you have tools for all of these:

Recipe & plate costing
- save_recipe_tool / cost_recipe_tool: save recipes and cost them against live
  OFN marketplace prices.

Seasonal sourcing
- seasonal_menu_tool: what's actively listed on OFN right now in the chef's
  state. Use when the chef asks "what's local", "what should I put on the menu".

Par levels & restocking
- set_par_tool / check_par_levels_tool / draft_restock_order_tool: chef-side
  inventory with par thresholds + multi-farm restock cart suggestions.

Provenance cards
- provenance_cards_tool: "meet your farmers" markdown cards for a comma-list
  of ingredients.

Account changes
- update_restaurant_profile_tool: edit the restaurant's OFN profile — name,
  description, slogan, website. Confirm details with the chef before calling.

Knowledge base
- pairsley_knowledge_tool: search your curated professional-kitchen library
  for "how do I / best practice" questions.

Style guidelines:
- Respond in 2-5 sentences unless the user explicitly asks for more.
- Use plain sentences. No markdown headers, no asterisks, no bullet lists
  unless the user asks for a list. Tool output is already formatted — you can
  quote it inline.
- If a user asks for an account change that feels risky (renaming the whole
  business, changing the primary website), confirm once before calling the tool.

business_id and people_id are injected automatically — the user will never need
to type them."""


# ---------------------------------------------------------------------------
# Core chat loop (ReAct)
# ---------------------------------------------------------------------------

def _load_chef_tools():
    """Late-import chef tools so that a chef.py import failure doesn't crash
    Pairsley start-up."""
    try:
        from chef import chef_tools, save_recipe_tool, cost_recipe_tool, \
            seasonal_menu_tool, set_par_tool, check_par_levels_tool, \
            draft_restock_order_tool, provenance_cards_tool
        return {
            "tools": chef_tools,
            "save_recipe_tool": save_recipe_tool,
            "cost_recipe_tool": cost_recipe_tool,
            "seasonal_menu_tool": seasonal_menu_tool,
            "set_par_tool": set_par_tool,
            "check_par_levels_tool": check_par_levels_tool,
            "draft_restock_order_tool": draft_restock_order_tool,
            "provenance_cards_tool": provenance_cards_tool,
        }
    except Exception as e:
        logger.error("[Pairsley] chef tools unavailable: %s", e)
        return {"tools": []}


def _render_short_term(messages: List[Dict[str, Any]]) -> str:
    """Render the last-N short-term messages as a transcript block."""
    if not messages:
        return ""
    lines = ["Recent conversation (most recent last):"]
    for m in messages[-SHORT_TERM_N:]:
        role = m.get("role", "user")
        content = (m.get("content") or "").strip()
        if not content:
            continue
        lines.append(f"{role.upper()}: {content}")
    return "\n".join(lines)


def respond(
    user_input: str,
    thread_id: str,
    user_id: str,
    business_id: Optional[int] = None,
    max_iterations: int = 4,
) -> Dict[str, Any]:
    """Run one Pairsley chat turn.

    Persists the user message, runs a ReAct tool loop (reusing chef tools +
    Pairsley-specific tools), persists the assistant reply, and returns a
    JSON-ready dict.
    """
    turn_start = time.monotonic()
    bid = 0
    try:
        bid = int(business_id or 0)
    except (TypeError, ValueError):
        bid = 0

    # Persist user message up front (short + long term)
    pairsley_chat_history.save_message(
        user_id=user_id, thread_id=thread_id, role="user", content=user_input,
    )
    push_message(thread_id=thread_id, message={"role": "user", "content": user_input})

    # Load short-term + RAG context
    last_n = get_last_n(thread_id, SHORT_TERM_N) or []
    short_term = _render_short_term(last_n)
    try:
        rag_ctx = rag_pairsley.get_context_for_query(user_input) or ""
    except Exception as e:
        logger.error("[Pairsley] RAG error: %s", e)
        rag_ctx = ""

    # Bind tools
    chef = _load_chef_tools()
    bound_tools = list(pairsley_own_tools) + list(chef.get("tools") or [])
    llm_with_tools = llm.bind_tools(bound_tools) if bound_tools else llm

    # Build prompt
    prompt_parts = [PAIRSLEY_SYSTEM_PROMPT]
    if short_term:
        prompt_parts.append(f"\n[Short-term memory]\n{short_term}")
    if rag_ctx:
        prompt_parts.append(f"\n[Knowledge base]\n{rag_ctx}")
    prompt_parts.append(f"\n[Current user message]\n{user_input}")
    current_input = "\n".join(prompt_parts)

    tool_results_context = ""
    final_response = ""

    try:
        for iteration in range(max_iterations):
            composed = current_input
            if tool_results_context:
                composed += f"\n\n[Tool results]\n{tool_results_context}"
            response = llm_with_tools.invoke(composed)

            tool_calls = getattr(response, "tool_calls", None) or []
            if tool_calls and iteration < max_iterations - 1:
                for tc in tool_calls:
                    name = tc.get("name")
                    args = tc.get("args", {}) or {}
                    result = _dispatch_tool(name, args, user_id, bid, chef)
                    if result:
                        tool_results_context = (
                            (tool_results_context + "\n\n" if tool_results_context else "")
                            + f"[{name}]\n{result}"
                        )
                continue

            final_response = getattr(response, "content", None) or str(response)
            break
        else:
            final_response = getattr(response, "content", None) or str(response)
    except Exception as e:
        logger.error("[Pairsley] respond error: %s", e, exc_info=True)
        final_response = "I hit a snag pulling that together. Try rephrasing, or ask me something more specific."

    latency_ms = int((time.monotonic() - turn_start) * 1000)
    pairsley_chat_history.save_message(
        user_id=user_id, thread_id=thread_id, role="assistant",
        content=final_response, metadata={"latency_ms": latency_ms},
    )
    push_message(thread_id=thread_id, message={"role": "assistant", "content": final_response})

    return {
        "status": "ok",
        "thread_id": thread_id,
        "response": final_response,
        "latency_ms": latency_ms,
    }


def _dispatch_tool(
    name: str,
    args: Dict[str, Any],
    user_id: str,
    business_id: int,
    chef: Dict[str, Any],
) -> str:
    """Invoke one of Pairsley's tools with business_id/people_id injected."""
    try:
        if name == "pairsley_knowledge_tool":
            return pairsley_knowledge_tool.invoke({"query": args.get("query", "")})
        if name == "update_restaurant_profile_tool":
            return update_restaurant_profile_tool.invoke({
                "business_name": args.get("business_name", ""),
                "description":   args.get("description", ""),
                "slogan":        args.get("slogan", ""),
                "website":       args.get("website", ""),
                "business_id":   business_id,
            })
        if name == "save_recipe_tool" and chef.get("save_recipe_tool"):
            return chef["save_recipe_tool"].invoke({
                "name":          args.get("name", ""),
                "items_json":    args.get("items_json", ""),
                "portion_yield": int(args.get("portion_yield", 1) or 1),
                "menu_price":    float(args.get("menu_price", 0) or 0),
                "business_id":   business_id,
            })
        if name == "cost_recipe_tool" and chef.get("cost_recipe_tool"):
            return chef["cost_recipe_tool"].invoke({
                "recipe_name": args.get("recipe_name", ""),
                "business_id": business_id,
            })
        if name == "seasonal_menu_tool" and chef.get("seasonal_menu_tool"):
            return chef["seasonal_menu_tool"].invoke({
                "state":       args.get("state", ""),
                "category":    args.get("category", ""),
                "business_id": business_id,
                "limit":       int(args.get("limit", 20) or 20),
            })
        if name == "set_par_tool" and chef.get("set_par_tool"):
            return chef["set_par_tool"].invoke({
                "ingredient_name":       args.get("ingredient_name", ""),
                "unit":                  args.get("unit", ""),
                "on_hand":               float(args.get("on_hand", 0) or 0),
                "par_level":             float(args.get("par_level", 0) or 0),
                "reorder_at":            float(args.get("reorder_at", 0) or 0),
                "preferred_business_id": int(args.get("preferred_business_id", 0) or 0),
                "business_id":           business_id,
            })
        if name == "check_par_levels_tool" and chef.get("check_par_levels_tool"):
            return chef["check_par_levels_tool"].invoke({"business_id": business_id})
        if name == "draft_restock_order_tool" and chef.get("draft_restock_order_tool"):
            return chef["draft_restock_order_tool"].invoke({"business_id": business_id})
        if name == "provenance_cards_tool" and chef.get("provenance_cards_tool"):
            return chef["provenance_cards_tool"].invoke({
                "ingredient_names": args.get("ingredient_names", ""),
            })
    except Exception as e:
        logger.error("[Pairsley] tool %s failed: %s", name, e)
        return f"(tool {name} failed: {e})"
    return f"(unknown tool: {name})"


# ---------------------------------------------------------------------------
# Read helpers for the REST layer
# ---------------------------------------------------------------------------

def list_threads(user_id: str, limit: int = 20, cursor: Optional[str] = None) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    return pairsley_chat_history.get_threads(user_id, limit=limit, cursor=cursor)


def get_messages(user_id: str, thread_id: str, limit: int = 50, cursor: Optional[str] = None) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    return pairsley_chat_history.get_messages(user_id, thread_id, limit=limit, cursor=cursor)


def delete_thread(user_id: str, thread_id: str) -> bool:
    return pairsley_chat_history.delete_thread(user_id, thread_id)
