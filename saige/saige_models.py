# --- saige_models.py --- (State definition and Pydantic models for Saige AI agent)
from typing import TypedDict, List, Optional, Dict, Any
from pydantic import BaseModel, Field


# ============================================================================
# STATE DEFINITION
# ============================================================================

class FarmState(TypedDict, total=False):
    people_id: Optional[str]
    business_id: Optional[str]
    thread_id: Optional[str]
    user_name: Optional[str]           # "Jane Smith" — fetched from People table at session start
    """State for managing farm information and diagnostics"""
    farm_name: Optional[str]
    location: Optional[str]
    farm_size: Optional[str]
    crops: Optional[List[str]]
    current_issues: Optional[List[str]]
    history: Optional[List[str]]
    diagnosis: Optional[str]
    soil_info: Optional[Dict[str, Any]]
    weather_conditions: Optional[Dict[str, Any]]
    management_practices: Optional[List[str]]
    recommendations: Optional[List[str]]
    assessment_summary: Optional[str]
    advisory_type: Optional[str]
    long_term_memory: Optional[Dict[str, Any]]  # per-user memory
    org_memory: Optional[Dict[str, Any]]         # shared across all org members
    image_data: Optional[str]
    field_id: Optional[str]


# ============================================================================
# PYDANTIC MODELS
# ============================================================================

class AssessmentDecision(BaseModel):
    is_complete: bool = Field(description="True if enough information collected")
    question: str = Field(description="Question to ask. Required if is_complete=False")
    options: Optional[List[str]] = Field(default=None, description="3-4 options if is_complete=False")
    assessment_summary: Optional[str] = Field(default=None, description="Summary if is_complete=True")


class QueryClassification(BaseModel):
    category: str = Field(
        description=(
            "'weather', 'livestock', 'crops', 'soil', 'field', 'news', "
            "'bakasura', 'user_data', or 'mixed'"
        )
    )
    confidence: str = Field(description="'high' or 'low'")
    reasoning: str = Field(description="Brief explanation")


class WeatherQueryParsed(BaseModel):
    """Structured extraction of weather query details."""
    is_weather_query: bool = Field(description="True if this is primarily a weather-related question")
    location: Optional[str] = Field(default=None, description="City, region, or location mentioned (e.g., 'Hayward, California', 'New York')")
    is_forecast: bool = Field(default=False, description="True if asking about future weather (forecast, next days, tomorrow, etc.)")
    forecast_days: Optional[int] = Field(default=None, description="Number of days for forecast (1 for tomorrow, 7 for week, etc.). Convert months to days (1 month = 30 days).")
    has_farm_context: bool = Field(default=False, description="True if query also mentions crops, livestock, or farming")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Extraction confidence score from 0.0 to 1.0")


class QueryTypeClassification(BaseModel):
    """Structured classification of farmer's query for fast-tracking assessment."""
    query_type: str = Field(
        description=(
            "Type of query: 'weather', 'livestock', 'crops', 'soil', 'field', 'news', "
            "'user_data', 'mixed', or 'general'. "
            "Use 'user_data' for profile/account lookups (name, email, phone, address, business info). "
            "Use 'general' for greetings, Saige identity, or non-farming small talk. "
            "Use 'field' for precision ag, NDVI, satellite field monitoring."
        )
    )
    is_specific: bool = Field(
        description="True if the query contains enough detail to answer directly (specific crop, animal, symptom, or location named). False if too vague."
    )
    needs_clarification: bool = Field(
        description=(
            "True ONLY if the query is so vague that no useful answer is possible without more info. "
            "Default to False — most questions can be answered directly. "
            "DO set True for: 'help with my farm', 'something is wrong', 'what should I do' (no context). "
            "DO NOT set True for: 'best goat breeds for meat', 'my tomato leaves are yellow', "
            "'what is my user ID', 'how do I treat mastitis', 'what breeds suit hot climates'. "
            "General (non-farming) questions should ALWAYS have needs_clarification=False."
        )
    )
    items: List[str] = Field(
        default_factory=list,
        description="List of specific crops/animals mentioned (e.g., ['cattle'], ['tomato', 'maize']), empty list if none"
    )


class MapIntentDetection(BaseModel):
    """Fast binary classification: is this a request to navigate/zoom a map?"""
    is_map_navigation: bool = Field(
        description=(
            "True if the user is asking to zoom, pan, fly, navigate, center, or move a map "
            "to a specific location (city, address, zip code, region, country, etc.). "
            "False for farming questions, greetings, crop advice, or anything unrelated to map navigation."
        )
    )


class FollowUpEntityExtraction(BaseModel):
    """Extract entities and intent from follow-up user input."""
    is_answer: bool = Field(description="True if this is an answer to a previous question (location, crop, animal, etc.), False if it's a new question")
    entity_type: Optional[str] = Field(default=None, description="Type of entity if it's an answer: 'location', 'crop', 'animal', 'farm_size', or None")
    extracted_location: Optional[str] = Field(default=None, description="Extracted location (city, state, region) if present")
    extracted_crops: List[str] = Field(default_factory=list, description="Extracted crops/plants if present")
    extracted_animals: List[str] = Field(default_factory=list, description="Extracted animals/livestock if present")
    extracted_farm_size: Optional[str] = Field(default=None, description="Extracted farm size if present")
    is_new_question: bool = Field(description="True if this is a genuinely new question, not an answer")
