# --- graph.py --- (StateGraph construction and compilation)
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from saige_models import FarmState
from nodes import (
    assessment_node,
    routing_node,
    weather_advisory_node,
    livestock_advisory_node,
    crop_advisory_node,
    soil_advisory_node,
    field_advisory_node,
    mixed_advisory_node,
    bakasura_advisory_node,
    news_advisory_node,
    user_data_advisory_node,
    joke_node,
    route_after_assessment,
    route_to_advisory,
)
from config import REDIS_ENABLED, REDIS_AVAILABLE, get_redis_url, redis_connection_mode

print("[Graph] Building farm advisory graph...")

builder = StateGraph(FarmState)

# Add nodes
builder.add_node("assessment_node", assessment_node)
builder.add_node("routing_node", routing_node)
builder.add_node("weather_advisory_node", weather_advisory_node)
builder.add_node("livestock_advisory_node", livestock_advisory_node)
builder.add_node("crop_advisory_node", crop_advisory_node)
builder.add_node("soil_advisory_node", soil_advisory_node)
builder.add_node("field_advisory_node", field_advisory_node)
builder.add_node("mixed_advisory_node", mixed_advisory_node)
builder.add_node("bakasura_advisory_node", bakasura_advisory_node)
builder.add_node("news_advisory_node", news_advisory_node)
builder.add_node("user_data_advisory_node", user_data_advisory_node)
builder.add_node("joke_node", joke_node)

# Add edges
builder.add_edge(START, "assessment_node")

builder.add_conditional_edges(
    "assessment_node",
    route_after_assessment,
    {"assessment_node": "assessment_node", "routing_node": "routing_node"}
)

builder.add_conditional_edges(
    "routing_node",
    route_to_advisory,
    {
        "weather_advisory_node": "weather_advisory_node",
        "livestock_advisory_node": "livestock_advisory_node",
        "crop_advisory_node": "crop_advisory_node",
        "soil_advisory_node": "soil_advisory_node",
        "field_advisory_node": "field_advisory_node",
        "mixed_advisory_node": "mixed_advisory_node",
        "bakasura_advisory_node": "bakasura_advisory_node",
        "news_advisory_node": "news_advisory_node",
        "user_data_advisory_node": "user_data_advisory_node",
        "joke_node": "joke_node",
    }
)

builder.add_edge("weather_advisory_node", END)
builder.add_edge("livestock_advisory_node", END)
builder.add_edge("crop_advisory_node", END)
builder.add_edge("soil_advisory_node", END)
builder.add_edge("field_advisory_node", END)
builder.add_edge("mixed_advisory_node", END)
builder.add_edge("bakasura_advisory_node", END)
builder.add_edge("news_advisory_node", END)
builder.add_edge("user_data_advisory_node", END)
builder.add_edge("joke_node", END)

# Compile with checkpointing (Redis if available, otherwise MemorySaver)
if REDIS_ENABLED and REDIS_AVAILABLE:
    try:
        from langgraph.checkpoint.redis import RedisSaver
        redis_url = get_redis_url()
        checkpointer = RedisSaver(redis_url)
        # Ensure RediSearch indexes exist before any read/get_state calls.
        checkpointer.setup()
        print(f"[Graph] [INFO] Redis mode: {redis_connection_mode()}")
        print("[Graph] [OK] Using Redis checkpointing (persistent across restarts)")
        print("[Graph] [OK] Redis checkpoint indexes ready")
    except ImportError:
        print("[Graph] [WARN] langgraph-checkpoint-redis not installed, using MemorySaver")
        checkpointer = MemorySaver()
    except Exception as e:
        print(f"[Graph] [WARN] Redis checkpointing failed: {e}, using MemorySaver")
        checkpointer = MemorySaver()
else:
    checkpointer = MemorySaver()
    print("[Graph] Using MemorySaver (Redis disabled)")

graph = builder.compile(checkpointer=checkpointer)

# Export builder for fallback graph creation if needed
__all__ = ['graph', 'builder']

print("\n" + "=" * 60)
print("Farm Advisory Graph Compiled Successfully!")
print("=" * 60)
print("Features:")
print("  - User-driven assessment (open question -> contextual follow-ups)")
print("  - Hybrid routing (keyword matching + LLM fallback)")
print("  - Separate advisory nodes (weather/livestock/crops/mixed)")
print("  - Pure weather queries support (dedicated weather node)")
print("  - Livestock RAG integration (breed recommendations)")
print("  - Weather tool integration (LLM decides when to fetch weather)")
print("  - Enhanced state management (assessment_summary + advisory_type)")
print("=" * 60)

try:
    from IPython.display import Image, display

    graph_repr = graph.get_graph()
    png_bytes = graph_repr.draw_mermaid_png(output_file_path="farm_advisory_graph.png")
    display(Image(png_bytes))
    print("Graph visualization displayed and saved as 'farm_advisory_graph.png'")
except ImportError:
    pass
except Exception as e:
    print(f"Could not display graph: {e}")
