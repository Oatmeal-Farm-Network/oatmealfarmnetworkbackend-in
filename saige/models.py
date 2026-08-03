# Deprecated: all saige-internal code now imports from saige_models directly.
# This file is kept as a shim so that any stale .pyc or external reference
# still resolves — but it no longer shadows the main backend's models.py
# because server_all.py restores sys.modules['models'] in Phase 5.
from saige_models import (  # noqa: F401
    FarmState,
    AssessmentDecision,
    QueryClassification,
    WeatherQueryParsed,
    QueryTypeClassification,
    FollowUpEntityExtraction,
)
