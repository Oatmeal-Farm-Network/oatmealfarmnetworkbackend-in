"""
Page-template catalog for the WebsiteBuilder.

A template is a recipe for creating a page: metadata + a list of default blocks.
Most templates are compositions of existing block types (hero/content/links/contact).
A few association-specific block types (member_directory, pedigree_search,
fee_schedule) are rendered by dedicated widgets in the frontend.

Gating:
  `business_type_ids` is a list of BusinessTypeLookup.BusinessTypeID values this
  template applies to. None means universal. For the Wave 1 catalog, most
  association-specific pages gate on [1] (Agricultural association).

Keep copy short and helpful — users will rewrite it. The goal is to seed the
page structure so the user isn't staring at an empty page.
"""

from typing import Any, Dict, List, Optional


# BusinessTypeIDs — kept in one place so templates read like plain English
BT_ASSOCIATION = 1
BT_FARM_RANCH = 8
BT_RESTAURANT = 9
BT_FOOD_HUB = 10
BT_ARTISAN_FOOD = 11
BT_FOOD_COOP = 14
BT_CRAFTERS_ORG = 15
BT_MANUFACTURER = 16
BT_VETERINARIAN = 17
BT_FIBER_MILL = 18
BT_MEAT_WHOLESALER = 19
BT_SERVICE_PROVIDER = 20
BT_MARINA = 21
BT_FISHERY = 22
BT_FISHERMEN = 23
BT_RETAILER = 24
BT_FIBER_COOP = 25
BT_GROCERY = 26
BT_UNIVERSITY = 27
BT_BUSINESS_RESOURCES = 28
BT_FARMERS_MARKET = 29
BT_REAL_ESTATE = 30
BT_HERB_TEA = 31
BT_TRANSPORTER = 32
BT_WINERY = 33
BT_VINEYARD = 34
BT_HUNGER_RELIEF = 35


PAGE_TEMPLATES: List[Dict[str, Any]] = [

    # ── Membership ────────────────────────────────────────────────────────
    {
        "key": "assoc_join_renew",
        "section": "Membership",
        "name": "Join / Renew",
        "slug": "join",
        "page_title": "Join or Renew Your Membership",
        "meta_description": "Choose a membership level and join our association — or renew your existing membership.",
        "business_type_ids": [BT_ASSOCIATION],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Become a Member",
                "subtext": "Support the breed, connect with other breeders, and access members-only resources.",
                "cta_text": "View Membership Levels",
                "cta_link": "#levels",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content_4col", "block_data": {"columns": [
                {"heading": "Active Breeder", "body": "For registered breeders with animals in the registry. Full voting rights."},
                {"heading": "Associate", "body": "For enthusiasts, supporters, and prospective breeders."},
                {"heading": "Junior", "body": "For members under 18. Discounted dues; eligible for youth programs."},
                {"heading": "Lifetime", "body": "One-time payment; supports the association in perpetuity."},
            ]}},
            {"block_type": "content", "block_data": {
                "heading": "How to join",
                "body": "Select your level, complete the application, and pay dues online. You'll receive a welcome packet and members-only login within 2 business days.",
            }},
            {"block_type": "contact", "block_data": {
                "heading": "Questions about membership?",
                "body": "Contact the membership office — we're happy to help you pick the right level.",
            }},
        ],
    },
    {
        "key": "assoc_member_benefits",
        "section": "Membership",
        "name": "Member Benefits",
        "slug": "benefits",
        "page_title": "Member Benefits",
        "meta_description": "What you get when you join — discounts, toolkits, insurance, directory listing, and more.",
        "business_type_ids": [BT_ASSOCIATION],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "What Your Membership Includes",
                "subtext": "Real tools, real savings, real community.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content_2col", "block_data": {"columns": [
                {"heading": "Discounts & Programs", "body": "Vendor discounts, group insurance, discounted registry fees, marketplace fee waivers."},
                {"heading": "Tools & Toolkits", "body": "Logo use, marketing kits, breed standards, health and welfare guides."},
            ]}},
            {"block_type": "content_2col", "block_data": {"columns": [
                {"heading": "Community", "body": "Member directory, mentorship, regional chapters, committees, youth programs."},
                {"heading": "Events", "body": "Discounted registration for the annual convention, shows, and clinics."},
            ]}},
        ],
    },
    {
        "key": "assoc_member_directory",
        "section": "Membership",
        "name": "Member Directory",
        "slug": "directory",
        "page_title": "Member Directory",
        "meta_description": "Find association members by region, breed, or service.",
        "business_type_ids": [BT_ASSOCIATION],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Find a Member",
                "subtext": "Search our member directory by region, breed, or specialty.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "member_directory", "block_data": {
                "heading": "", "filter_by": ["region", "specialty"],
                "show_map": True, "results_per_page": 25,
            }},
        ],
    },
    {
        "key": "assoc_chapters",
        "section": "Membership",
        "name": "Chapters & Regional Groups",
        "slug": "chapters",
        "business_type_ids": [BT_ASSOCIATION],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Regional Chapters", "subtext": "Find your local group.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "links", "block_data": {"links": [
                {"title": "Pacific Northwest", "description": "WA, OR, ID", "url": "#", "icon": "🌲"},
                {"title": "Midwest", "description": "MN, WI, IA, IL", "url": "#", "icon": "🌾"},
                {"title": "Northeast", "description": "NY, PA, NJ, New England", "url": "#", "icon": "🍂"},
                {"title": "Southeast", "description": "NC, SC, GA, FL, TN", "url": "#", "icon": "🌞"},
            ]}},
        ],
    },

    # ── About the Organization ────────────────────────────────────────────
    {
        "key": "assoc_board_of_directors",
        "section": "About",
        "name": "Board of Directors",
        "slug": "board",
        "page_title": "Board of Directors",
        "meta_description": "Meet the elected leaders who guide the association.",
        "business_type_ids": [BT_ASSOCIATION],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Our Board", "subtext": "Elected breeders and industry leaders who set association direction.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content_2col", "block_data": {"columns": [
                {"heading": "President", "body": "[Name]\n\nShort bio goes here. Term ends 2026."},
                {"heading": "Vice President", "body": "[Name]\n\nShort bio goes here. Term ends 2027."},
            ]}},
            {"block_type": "content_2col", "block_data": {"columns": [
                {"heading": "Treasurer", "body": "[Name]\n\nShort bio. Term ends 2026."},
                {"heading": "Secretary", "body": "[Name]\n\nShort bio. Term ends 2027."},
            ]}},
        ],
    },
    {
        "key": "assoc_bylaws",
        "section": "About",
        "name": "Bylaws & Constitution",
        "slug": "bylaws",
        "business_type_ids": [BT_ASSOCIATION],
        "default_blocks": [
            {"block_type": "content", "block_data": {
                "heading": "Bylaws & Constitution",
                "body": "The governing documents of the association. Download the current version (PDF) and review amendment history.\n\n[Replace this text with your bylaws summary. Link to the PDF via the file manager.]",
            }},
        ],
    },
    {
        "key": "assoc_code_of_ethics",
        "section": "About",
        "name": "Code of Ethics",
        "slug": "ethics",
        "business_type_ids": [BT_ASSOCIATION],
        "default_blocks": [
            {"block_type": "content", "block_data": {
                "heading": "Code of Ethics",
                "body": "Members agree to conduct themselves and their operations in accordance with the following standards:\n\n• Accurate representation of animals and products\n• Humane husbandry and welfare practices\n• Honest registry reporting\n• Fair and transparent sales practices\n\nReplace this with your full code.",
            }},
        ],
    },

    # ── Registrar ─────────────────────────────────────────────────────────
    {
        "key": "assoc_breed_standards",
        "section": "Registrar",
        "name": "Breed Standards",
        "slug": "breed-standards",
        "page_title": "Breed Standards",
        "meta_description": "Ideal conformation, color, and disqualifying traits for the breed.",
        "business_type_ids": [BT_ASSOCIATION],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Breed Standards",
                "subtext": "The reference for ideal conformation, color, and structure.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content_2col", "block_data": {"columns": [
                {"heading": "Head & Expression", "body": "Describe desired head shape, ears, eyes, and expression."},
                {"heading": "Body & Structure", "body": "Topline, chest width, depth of body, leg set."},
            ]}},
            {"block_type": "content_2col", "block_data": {"columns": [
                {"heading": "Coat & Color", "body": "Acceptable colors, patterns, fiber characteristics."},
                {"heading": "Temperament", "body": "Desired disposition and working traits."},
            ]}},
            {"block_type": "content", "block_data": {
                "heading": "Disqualifying Traits",
                "body": "List traits that disqualify an animal from registration or show.",
            }},
        ],
    },
    {
        "key": "assoc_online_registry",
        "section": "Registrar",
        "name": "Online Registry",
        "slug": "registry",
        "page_title": "Online Registry Database",
        "meta_description": "Search pedigrees, progeny records, and ownership history.",
        "business_type_ids": [BT_ASSOCIATION],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Pedigree Lookup",
                "subtext": "Search our registry for any registered animal.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "pedigree_search", "block_data": {
                "heading": "", "allow_registration_number": True,
                "allow_name_search": True, "show_progeny": True,
            }},
        ],
    },
    {
        "key": "assoc_register_animal",
        "section": "Registrar",
        "name": "Register an Animal",
        "slug": "register-animal",
        "business_type_ids": [BT_ASSOCIATION],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Register Your Animal",
                "subtext": "Forms and instructions for new registrations.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content", "block_data": {
                "heading": "Before you begin",
                "body": "Gather: sire and dam registration numbers, date of birth, sex, color/markings, microchip or tag ID.",
            }},
            {"block_type": "links", "block_data": {"links": [
                {"title": "New Birth Registration", "description": "Register an animal born to registered parents", "url": "#", "icon": "📝"},
                {"title": "Transfer of Ownership", "description": "Record a change of owner", "url": "/transfer", "icon": "🔄"},
                {"title": "Lost Certificate", "description": "Request a duplicate pedigree certificate", "url": "#", "icon": "📄"},
            ]}},
        ],
    },
    {
        "key": "assoc_fee_schedule",
        "section": "Registrar",
        "name": "Fee Schedule",
        "slug": "fees",
        "page_title": "Fee Schedule",
        "meta_description": "Transparent pricing for registration, transfer, and processing services.",
        "business_type_ids": [BT_ASSOCIATION],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Fee Schedule",
                "subtext": "Transparent pricing for all registry and association services.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "fee_schedule", "block_data": {
                "heading": "", "currency": "USD",
                "items": [
                    {"service": "New registration (under 6 months)", "member_fee": 15, "non_member_fee": 30},
                    {"service": "New registration (over 6 months)",  "member_fee": 30, "non_member_fee": 50},
                    {"service": "Transfer of ownership",               "member_fee": 10, "non_member_fee": 25},
                    {"service": "Duplicate certificate",               "member_fee": 10, "non_member_fee": 20},
                    {"service": "DNA / parentage test",                "member_fee": 40, "non_member_fee": 55},
                ],
            }},
        ],
    },

    # ── Events (association-flavored) ─────────────────────────────────────
    {
        "key": "assoc_annual_convention",
        "section": "Events",
        "name": "Annual Convention",
        "slug": "convention",
        "business_type_ids": [BT_ASSOCIATION],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Annual Convention & Trade Show",
                "subtext": "Three days of education, community, and industry networking.",
                "cta_text": "Register", "cta_link": "#register",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content_4col", "block_data": {"columns": [
                {"heading": "Dates", "body": "[Date range]"},
                {"heading": "Location", "body": "[City, State]\n[Venue name]"},
                {"heading": "Hotel", "body": "[Hotel name]\nGroup rate available"},
                {"heading": "Exhibitor Info", "body": "[Link to exhibitor packet]"},
            ]}},
            {"block_type": "events", "block_data": {
                "heading": "Convention schedule",
                "layout": "list", "max_items": 20,
            }},
        ],
    },
    {
        "key": "assoc_national_show",
        "section": "Events",
        "name": "National Breed Show",
        "slug": "national-show",
        "business_type_ids": [BT_ASSOCIATION],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "National Breed Show",
                "subtext": "Our flagship conformation and performance event.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content_2col", "block_data": {"columns": [
                {"heading": "Entry forms", "body": "Download entry forms and submit with fees by the posted deadline."},
                {"heading": "Stalling & camping", "body": "Reserve stalls and RV sites when you enter."},
            ]}},
        ],
    },
    {
        "key": "assoc_workshops",
        "section": "Events",
        "name": "Workshops & Certifications",
        "slug": "workshops",
        "business_type_ids": [BT_ASSOCIATION],
        "default_blocks": [
            {"block_type": "content", "block_data": {
                "heading": "Workshops & Certifications",
                "body": "BQA, FAMACHA, ServSafe, and other certifications the association offers or co-hosts.",
            }},
            {"block_type": "events", "block_data": {
                "heading": "Upcoming workshops",
                "layout": "cards", "max_items": 12,
            }},
        ],
    },

    # ── Advocacy ──────────────────────────────────────────────────────────
    {
        "key": "assoc_legislative_priorities",
        "section": "Advocacy",
        "name": "Legislative Priorities",
        "slug": "legislative-priorities",
        "business_type_ids": [BT_ASSOCIATION],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Our Policy Priorities",
                "subtext": "Current positions on state and federal legislation.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content", "block_data": {
                "heading": "Current priorities",
                "body": "• Priority 1 — brief description\n• Priority 2 — brief description\n• Priority 3 — brief description",
            }},
        ],
    },
    {
        "key": "assoc_action_alerts",
        "section": "Advocacy",
        "name": "Action Alerts",
        "slug": "action-alerts",
        "business_type_ids": [BT_ASSOCIATION],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Take Action",
                "subtext": "Time-sensitive calls to contact representatives or submit public comment.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content", "block_data": {
                "heading": "No active alerts",
                "body": "When a bill needs member action, it will appear here with a direct link and talking points.",
            }},
        ],
    },

    # ── Co-op / Commodity Collection ──────────────────────────────────────
    {
        "key": "assoc_shearing_schedule",
        "section": "Co-op",
        "name": "Shearing Schedule",
        "slug": "shearing",
        "business_type_ids": [BT_ASSOCIATION],
        "default_blocks": [
            {"block_type": "content", "block_data": {
                "heading": "Mobile Shearing Schedule",
                "body": "Regional shearing dates, drop-off windows, and contact info for each stop.",
            }},
            {"block_type": "events", "block_data": {
                "heading": "Upcoming shearing dates",
                "layout": "list", "max_items": 20,
            }},
        ],
    },
    {
        "key": "assoc_dropoff_locations",
        "section": "Co-op",
        "name": "Drop-off Locations",
        "slug": "dropoff",
        "business_type_ids": [BT_ASSOCIATION],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Fiber Drop-off Locations",
                "subtext": "Regional warehouses and collection points.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "links", "block_data": {"links": [
                {"title": "Pacific Northwest warehouse", "description": "Address, hours", "url": "#", "icon": "📍"},
                {"title": "Midwest collection point",      "description": "Address, hours", "url": "#", "icon": "📍"},
                {"title": "Northeast collection point",    "description": "Address, hours", "url": "#", "icon": "📍"},
            ]}},
        ],
    },
    {
        "key": "assoc_grading_standards",
        "section": "Co-op",
        "name": "Grading & Sorting Standards",
        "slug": "grading-standards",
        "business_type_ids": [BT_ASSOCIATION],
        "default_blocks": [
            {"block_type": "content_2col", "block_data": {"columns": [
                {"heading": "Skirting", "body": "How to skirt a fleece before delivery."},
                {"heading": "Micron & staple length", "body": "Acceptable ranges and grading tiers."},
            ]}},
            {"block_type": "content", "block_data": {
                "heading": "Penalties",
                "body": "Second cuts, vegetable matter, and contamination affect grade and payout.",
            }},
        ],
    },

    # ── Education ─────────────────────────────────────────────────────────
    {
        "key": "assoc_glossary",
        "section": "Education",
        "name": "Industry Glossary",
        "slug": "glossary",
        "business_type_ids": [BT_ASSOCIATION],
        "default_blocks": [
            {"block_type": "content", "block_data": {
                "heading": "Glossary",
                "body": "Key industry terms, in alphabetical order. Add or edit entries as needed.",
            }},
        ],
    },
    {
        "key": "assoc_faq",
        "section": "Education",
        "name": "Member FAQ",
        "slug": "member-faq",
        "business_type_ids": [BT_ASSOCIATION],
        "default_blocks": [
            {"block_type": "content", "block_data": {
                "heading": "Frequently Asked Questions",
                "body": "Add questions and answers that come up often. Group by topic for easier scanning.",
            }},
        ],
    },

    # ── Foundation ────────────────────────────────────────────────────────
    {
        "key": "assoc_donation",
        "section": "Foundation",
        "name": "Donation Page",
        "slug": "donate",
        "business_type_ids": [BT_ASSOCIATION],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Support Our Mission",
                "subtext": "Your gift funds research, youth programs, and disaster relief.",
                "cta_text": "Donate", "cta_link": "#donate",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content_2col", "block_data": {"columns": [
                {"heading": "One-time gifts", "body": "Pick any amount. 100% of your gift supports the foundation."},
                {"heading": "Planned giving", "body": "Bequests, endowments, memorial gifts — contact us to discuss."},
            ]}},
            {"block_type": "contact", "block_data": {
                "heading": "Questions about giving?",
                "body": "Our foundation office can walk you through options and tax-deductibility.",
            }},
        ],
    },
    {
        "key": "assoc_scholarships",
        "section": "Foundation",
        "name": "Scholarships",
        "slug": "scholarships",
        "business_type_ids": [BT_ASSOCIATION],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Scholarships for the Next Generation",
                "subtext": "Annual scholarships for junior members pursuing ag or animal sciences.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content", "block_data": {
                "heading": "How to apply",
                "body": "Eligibility, requirements, deadlines, and the application packet. Review the FAQ at the bottom before submitting.",
            }},
            {"block_type": "content_2col", "block_data": {"columns": [
                {"heading": "Past recipients", "body": "Celebrate last year's awardees and their programs of study."},
                {"heading": "Donor recognition", "body": "Our scholarships are made possible by named gifts. Learn how to endow one."},
            ]}},
        ],
    },

    # ── Youth ─────────────────────────────────────────────────────────────
    {
        "key": "assoc_youth_programs",
        "section": "Youth",
        "name": "Youth Programs",
        "slug": "youth",
        "business_type_ids": [BT_ASSOCIATION],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Growing the Next Generation",
                "subtext": "Showmanship, judging contests, scholarships, and hands-on learning for junior members.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content_4col", "block_data": {"columns": [
                {"heading": "Shows & Contests", "body": "Youth show classes, skillathons, and judging competitions."},
                {"heading": "Leadership", "body": "Junior ambassador program — apply each spring."},
                {"heading": "Scholarships", "body": "Annual awards for members pursuing ag sciences."},
                {"heading": "Camps & Clinics", "body": "Summer camps and regional clinics across the country."},
            ]}},
            {"block_type": "contact", "block_data": {
                "heading": "Get your youth involved",
                "body": "Contact our youth coordinator to enroll or volunteer.",
            }},
        ],
    },
    {
        "key": "assoc_junior_ambassador",
        "section": "Youth",
        "name": "Junior Ambassador Program",
        "slug": "junior-ambassador",
        "business_type_ids": [BT_ASSOCIATION],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Become a Junior Ambassador",
                "subtext": "Represent the breed at shows, events, and on social media.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content", "block_data": {
                "heading": "Application & requirements",
                "body": "Age requirements, commitment expectations, and how ambassadors are selected each year.",
            }},
            {"block_type": "content", "block_data": {
                "heading": "Meet this year's team",
                "body": "Photos and bios of the current ambassadors.",
            }},
        ],
    },

    # ── Committees ────────────────────────────────────────────────────────
    {
        "key": "assoc_committees",
        "section": "Committees",
        "name": "Committees Overview",
        "slug": "committees",
        "business_type_ids": [BT_ASSOCIATION],
        "default_blocks": [
            {"block_type": "content", "block_data": {
                "heading": "Committees",
                "body": "Our committees do the real work of the association. Members are welcome to join or observe.",
            }},
            {"block_type": "content_4col", "block_data": {"columns": [
                {"heading": "Breed Standards", "body": "Review and recommend changes to the official standard."},
                {"heading": "Registry & DNA",  "body": "Oversee registration rules, parentage verification, and inspection program."},
                {"heading": "Youth",           "body": "Plan youth shows, scholarships, and the ambassador program."},
                {"heading": "Show",            "body": "Approve judges, rules, and premium lists for sanctioned shows."},
            ]}},
            {"block_type": "contact", "block_data": {
                "heading": "Want to serve?",
                "body": "Committee appointments are made annually. Contact the board to express interest.",
            }},
        ],
    },

    # ── Registrar (additions) ─────────────────────────────────────────────
    {
        "key": "assoc_transfer_of_ownership",
        "section": "Registrar",
        "name": "Transfer of Ownership",
        "slug": "transfer",
        "business_type_ids": [BT_ASSOCIATION],
        "default_blocks": [
            {"block_type": "content", "block_data": {
                "heading": "Transfer an Animal's Registration",
                "body": "Step-by-step: seller completes the transfer form, buyer pays the transfer fee, registry updates ownership and issues a new certificate.",
            }},
            {"block_type": "links", "block_data": {"heading": "Forms", "columns": 2, "groups": [
                {"heading": "Downloads", "items": [
                    {"label": "Transfer of Ownership Form", "url": "#", "description": "PDF — seller & buyer signatures required."},
                    {"label": "Bill of Sale Template",      "url": "#", "description": "Optional; helpful for resale records."},
                ]},
            ]}},
        ],
    },
    {
        "key": "assoc_dna_parentage",
        "section": "Registrar",
        "name": "DNA & Parentage Testing",
        "slug": "dna",
        "business_type_ids": [BT_ASSOCIATION],
        "default_blocks": [
            {"block_type": "content", "block_data": {
                "heading": "DNA Testing & Parentage Verification",
                "body": "Required for registration in certain classes. Here's our accepted lab, sample submission process, and how results are recorded with the registry.",
            }},
            {"block_type": "content_2col", "block_data": {"columns": [
                {"heading": "Submitting samples", "body": "Order kits, collect samples correctly, and submit with the registry form."},
                {"heading": "Reading results",    "body": "How to interpret exclusion results and what to do if parentage cannot be confirmed."},
            ]}},
        ],
    },
    {
        "key": "assoc_inspections",
        "section": "Registrar",
        "name": "Animal Inspections",
        "slug": "inspections",
        "business_type_ids": [BT_ASSOCIATION],
        "default_blocks": [
            {"block_type": "content", "block_data": {
                "heading": "Animal Inspection Program",
                "body": "Inspections confirm that an animal meets the breed standard. Schedule an inspection, see current inspectors, and view fee rates.",
            }},
            {"block_type": "content_2col", "block_data": {"columns": [
                {"heading": "Scheduling",   "body": "How to request an on-farm or event inspection."},
                {"heading": "What to expect", "body": "Documentation, measurements, and the approval workflow."},
            ]}},
        ],
    },

    # ── Industry ──────────────────────────────────────────────────────────
    {
        "key": "assoc_market_reports",
        "section": "Industry",
        "name": "Market Reports",
        "slug": "market-reports",
        "business_type_ids": [BT_ASSOCIATION],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Market & Industry Reports",
                "subtext": "Quarterly trend data, sale averages, and industry benchmarks for members.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content", "block_data": {
                "heading": "Latest report",
                "body": "Summary + download link for the most recent quarterly report.",
            }},
            {"block_type": "content", "block_data": {
                "heading": "Archive",
                "body": "Prior reports organized by year. Members log in to download full datasets.",
            }},
        ],
    },
    {
        "key": "assoc_research",
        "section": "Industry",
        "name": "Research & Studies",
        "slug": "research",
        "business_type_ids": [BT_ASSOCIATION],
        "default_blocks": [
            {"block_type": "content", "block_data": {
                "heading": "Research the Association Supports",
                "body": "Ongoing studies, partnerships with universities, and findings members can put to work.",
            }},
            {"block_type": "content_2col", "block_data": {"columns": [
                {"heading": "Active studies",   "body": "What's being studied right now and how members can participate."},
                {"heading": "Published papers", "body": "Links to journal articles and plain-English summaries."},
            ]}},
        ],
    },

    # ── Shows (sub-pages of Events) ───────────────────────────────────────
    {
        "key": "assoc_show_rules",
        "section": "Events",
        "name": "Show Rules & Classes",
        "slug": "show-rules",
        "business_type_ids": [BT_ASSOCIATION],
        "default_blocks": [
            {"block_type": "content", "block_data": {
                "heading": "Show Rules & Class Descriptions",
                "body": "The official rules every exhibitor should read before entering: eligibility, class structure, scoring, and disciplinary procedures.",
            }},
            {"block_type": "content_2col", "block_data": {"columns": [
                {"heading": "Halter classes",      "body": "By age and sex. Handler attire, leading, and ring etiquette."},
                {"heading": "Performance classes", "body": "Obstacle, public relations, showmanship — rules and scoring rubrics."},
            ]}},
        ],
    },
    {
        "key": "assoc_judges",
        "section": "Events",
        "name": "Approved Judges",
        "slug": "judges",
        "business_type_ids": [BT_ASSOCIATION],
        "default_blocks": [
            {"block_type": "content", "block_data": {
                "heading": "Approved Judges",
                "body": "Roster of judges approved to officiate at sanctioned shows. Shows must hire from this list.",
            }},
            {"block_type": "content", "block_data": {
                "heading": "Becoming a judge",
                "body": "The apprenticeship program, examinations, and continuing education requirements.",
            }},
        ],
    },

    # ── Advocacy (addition) ───────────────────────────────────────────────
    {
        "key": "assoc_disaster_relief",
        "section": "Advocacy",
        "name": "Disaster Relief Fund",
        "slug": "disaster-relief",
        "business_type_ids": [BT_ASSOCIATION],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Members Helping Members",
                "subtext": "When disaster strikes — fire, flood, disease outbreak — our relief fund helps members rebuild.",
                "cta_text": "Donate", "cta_link": "#donate",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content_2col", "block_data": {"columns": [
                {"heading": "Apply for aid",  "body": "Eligibility, documentation, and how funds are distributed."},
                {"heading": "Contribute",     "body": "One-time or recurring gifts fuel the fund year-round."},
            ]}},
        ],
    },

    # ── Core / Public (universal) ─────────────────────────────────────────
    {
        "key": "core_home_welcome",
        "section": "Core",
        "name": "Homepage — Welcome",
        "slug": "home",
        "page_title": "Welcome",
        "business_type_ids": None,
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Welcome",
                "subtext": "A short tagline that tells a first-time visitor what you do and who you serve.",
                "cta_text": "Learn More", "cta_link": "/about",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content_3col", "block_data": {"columns": [
                {"heading": "What we do",  "body": "Two or three sentences about your focus area."},
                {"heading": "Who we serve", "body": "The customers, members, or community you work with."},
                {"heading": "Why it matters", "body": "The story or mission behind the work."},
            ]}},
            {"block_type": "contact", "block_data": {
                "heading": "Get in touch",
                "body": "We'd love to hear from you — questions, collaborations, or just to say hello.",
            }},
        ],
    },
    {
        "key": "core_about",
        "section": "Core",
        "name": "About Us",
        "slug": "about",
        "page_title": "About Us",
        "business_type_ids": None,
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "About Us",
                "subtext": "Our story, in short.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content", "block_data": {
                "heading": "Our story",
                "body": "Where we started, what we've built, and where we're headed.",
            }},
            {"block_type": "content_2col", "block_data": {"columns": [
                {"heading": "Mission",  "body": "What we work toward every day."},
                {"heading": "Values",   "body": "The principles that guide how we operate."},
            ]}},
        ],
    },
    {
        "key": "core_contact",
        "section": "Core",
        "name": "Contact",
        "slug": "contact",
        "page_title": "Contact Us",
        "business_type_ids": None,
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Contact Us",
                "subtext": "We'll get back to you within 1–2 business days.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "contact", "block_data": {
                "heading": "Send us a message",
                "body": "Questions, feedback, or requests — send them here.",
            }},
            {"block_type": "map_location", "block_data": {
                "heading": "Find Us",
                "address": "",
                "embed_url": "",
                "height": 320,
            }},
        ],
    },
    {
        "key": "core_faq",
        "section": "Core",
        "name": "FAQ",
        "slug": "faq",
        "page_title": "Frequently Asked Questions",
        "business_type_ids": None,
        "default_blocks": [
            {"block_type": "content", "block_data": {
                "heading": "Frequently Asked Questions",
                "body": "The questions we hear most often — if yours isn't here, just ask.",
            }},
            {"block_type": "content_2col", "block_data": {"columns": [
                {"heading": "Question 1", "body": "A clear, short answer."},
                {"heading": "Question 2", "body": "A clear, short answer."},
            ]}},
            {"block_type": "content_2col", "block_data": {"columns": [
                {"heading": "Question 3", "body": "A clear, short answer."},
                {"heading": "Question 4", "body": "A clear, short answer."},
            ]}},
        ],
    },
    {
        "key": "core_privacy",
        "section": "Core",
        "name": "Privacy Policy",
        "slug": "privacy",
        "page_title": "Privacy Policy",
        "business_type_ids": None,
        "default_blocks": [
            {"block_type": "content", "block_data": {
                "heading": "Privacy Policy",
                "body": "This page explains what information we collect, how we use it, and your rights. Replace this placeholder with your own policy or have legal counsel review before publishing.",
            }},
        ],
    },
    {
        "key": "core_terms",
        "section": "Core",
        "name": "Terms of Service",
        "slug": "terms",
        "page_title": "Terms of Service",
        "business_type_ids": None,
        "default_blocks": [
            {"block_type": "content", "block_data": {
                "heading": "Terms of Service",
                "body": "These terms govern use of this site and any services offered here. Replace this placeholder with your own terms or have legal counsel review before publishing.",
            }},
        ],
    },

    # ── Commerce (universal) ──────────────────────────────────────────────
    {
        "key": "commerce_store",
        "section": "Commerce",
        "name": "Online Store",
        "slug": "store",
        "page_title": "Shop",
        "business_type_ids": None,
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Shop",
                "subtext": "Browse our products and place an order online.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content", "block_data": {
                "heading": "Featured products",
                "body": "Add product images and descriptions, or embed your store widget here.",
            }},
        ],
    },
    {
        "key": "commerce_services",
        "section": "Commerce",
        "name": "Services",
        "slug": "services",
        "page_title": "Our Services",
        "business_type_ids": None,
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Our Services",
                "subtext": "What we offer and who we help.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content_3col", "block_data": {"columns": [
                {"heading": "Service 1", "body": "What it is and who it's for."},
                {"heading": "Service 2", "body": "What it is and who it's for."},
                {"heading": "Service 3", "body": "What it is and who it's for."},
            ]}},
            {"block_type": "contact", "block_data": {
                "heading": "Request a quote",
                "body": "Tell us what you need and we'll get back to you with pricing and scheduling.",
            }},
        ],
    },
    {
        "key": "commerce_pricing",
        "section": "Commerce",
        "name": "Pricing",
        "slug": "pricing",
        "page_title": "Pricing",
        "business_type_ids": None,
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Pricing",
                "subtext": "Simple, transparent pricing.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "fee_schedule", "block_data": {
                "heading": "Price list",
                "rows": [
                    {"item": "Starter",   "amount": "$—",  "notes": "Basic package."},
                    {"item": "Standard",  "amount": "$—",  "notes": "Most popular."},
                    {"item": "Premium",   "amount": "$—",  "notes": "Full-service."},
                ],
            }},
        ],
    },

    # ── Standards & Health (assoc) ────────────────────────────────────────
    {
        "key": "assoc_breed_standard",
        "section": "Standards",
        "name": "Breed Standard",
        "slug": "breed-standard",
        "page_title": "Breed Standard",
        "business_type_ids": [BT_ASSOCIATION],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Breed Standard",
                "subtext": "The official description of the ideal animal — the benchmark for judging and breeding decisions.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content_2col", "block_data": {"columns": [
                {"heading": "General appearance", "body": "Overall impression, balance, and type."},
                {"heading": "Structure",          "body": "Head, body, legs, feet — what to look for and what to avoid."},
            ]}},
            {"block_type": "content_2col", "block_data": {"columns": [
                {"heading": "Coat & color",       "body": "Acceptable patterns, colors, and disqualifications."},
                {"heading": "Temperament",        "body": "Disposition and behavioral traits consistent with the breed."},
            ]}},
        ],
    },
    {
        "key": "assoc_health_welfare",
        "section": "Standards",
        "name": "Health & Welfare",
        "slug": "health-welfare",
        "business_type_ids": [BT_ASSOCIATION],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Health & Welfare",
                "subtext": "Guidelines our members follow to keep animals healthy and well-cared-for.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content_2col", "block_data": {"columns": [
                {"heading": "Husbandry",  "body": "Housing, nutrition, and routine care expectations."},
                {"heading": "Veterinary", "body": "Vaccination schedules, parasite control, and required testing."},
            ]}},
            {"block_type": "content", "block_data": {
                "heading": "Reporting welfare concerns",
                "body": "How to confidentially report suspected welfare issues for investigation.",
            }},
        ],
    },
    {
        "key": "assoc_genetic_defects",
        "section": "Standards",
        "name": "Known Genetic Conditions",
        "slug": "genetic-conditions",
        "business_type_ids": [BT_ASSOCIATION],
        "default_blocks": [
            {"block_type": "content", "block_data": {
                "heading": "Known genetic conditions",
                "body": "Conditions tracked by the association, testing expectations, and breeding guidance to reduce incidence.",
            }},
            {"block_type": "content_2col", "block_data": {"columns": [
                {"heading": "Required testing", "body": "What must be tested before registration or breeding."},
                {"heading": "Approved labs",    "body": "Labs accepted by the association and how to submit samples."},
            ]}},
        ],
    },

    # ── Library (assoc) ───────────────────────────────────────────────────
    {
        "key": "assoc_resource_library",
        "section": "Library",
        "name": "Resource Library",
        "slug": "resources",
        "page_title": "Resource Library",
        "business_type_ids": [BT_ASSOCIATION],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Resource Library",
                "subtext": "Toolkits, guides, templates, and research — curated for members.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "links", "block_data": {
                "heading": "Popular resources",
                "links": [
                    {"label": "New breeder starter kit", "url": "#"},
                    {"label": "Marketing templates",    "url": "#"},
                    {"label": "Record-keeping forms",   "url": "#"},
                ],
            }},
        ],
    },
    {
        "key": "assoc_newsletter_archive",
        "section": "Library",
        "name": "Newsletter Archive",
        "slug": "newsletters",
        "business_type_ids": [BT_ASSOCIATION],
        "default_blocks": [
            {"block_type": "content", "block_data": {
                "heading": "Newsletter Archive",
                "body": "Past issues of the member newsletter. Members receive each new issue by email.",
            }},
            {"block_type": "links", "block_data": {
                "heading": "Recent issues",
                "links": [
                    {"label": "Spring issue",  "url": "#"},
                    {"label": "Winter issue",  "url": "#"},
                    {"label": "Fall issue",    "url": "#"},
                ],
            }},
        ],
    },

    # ── Shows (assoc, additions to Events) ────────────────────────────────
    {
        "key": "assoc_show_results",
        "section": "Events",
        "name": "Show Results",
        "slug": "show-results",
        "business_type_ids": [BT_ASSOCIATION],
        "default_blocks": [
            {"block_type": "content", "block_data": {
                "heading": "Show Results",
                "body": "Results from sanctioned shows, organized by year and show.",
            }},
            {"block_type": "links", "block_data": {
                "heading": "Recent shows",
                "links": [
                    {"label": "National Show",   "url": "#"},
                    {"label": "Regional East",   "url": "#"},
                    {"label": "Regional West",   "url": "#"},
                ],
            }},
        ],
    },
    {
        "key": "assoc_point_standings",
        "section": "Events",
        "name": "Point Standings",
        "slug": "point-standings",
        "business_type_ids": [BT_ASSOCIATION],
        "default_blocks": [
            {"block_type": "content", "block_data": {
                "heading": "Year-End Point Standings",
                "body": "Accumulated show points toward year-end and lifetime awards.",
            }},
            {"block_type": "content_2col", "block_data": {"columns": [
                {"heading": "How points are calculated", "body": "Class placings, number of animals shown, and judge multipliers."},
                {"heading": "Awards & cutoffs",          "body": "Annual awards are based on points earned between Jan 1 and Dec 31."},
            ]}},
        ],
    },

    # ── Content (universal) ───────────────────────────────────────────────
    {
        "key": "core_blog",
        "section": "Content",
        "name": "Blog / News",
        "slug": "blog",
        "page_title": "Blog",
        "business_type_ids": None,
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "News & Updates",
                "subtext": "Stories, announcements, and deep dives.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content", "block_data": {
                "heading": "Latest posts",
                "body": "Add a blog widget here, or link out to your newsletter or external blog.",
            }},
        ],
    },
    {
        "key": "core_team",
        "section": "Content",
        "name": "Team / Staff",
        "slug": "team",
        "page_title": "Meet the Team",
        "business_type_ids": None,
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Meet the Team",
                "subtext": "The people behind the work.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content_3col", "block_data": {"columns": [
                {"heading": "Name — Role",  "body": "A sentence or two about this person's background and what they work on."},
                {"heading": "Name — Role",  "body": "A sentence or two about this person's background and what they work on."},
                {"heading": "Name — Role",  "body": "A sentence or two about this person's background and what they work on."},
            ]}},
        ],
    },
    {
        "key": "core_gallery",
        "section": "Content",
        "name": "Photo Gallery",
        "slug": "gallery",
        "page_title": "Gallery",
        "business_type_ids": None,
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Gallery",
                "subtext": "A visual tour of what we do.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content", "block_data": {
                "heading": "Photos",
                "body": "Add an image gallery widget, or swap in individual image blocks.",
            }},
        ],
    },
    {
        "key": "core_testimonials",
        "section": "Content",
        "name": "Testimonials",
        "slug": "testimonials",
        "business_type_ids": None,
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "What People Say",
                "subtext": "In their own words.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content_2col", "block_data": {"columns": [
                {"heading": "— Happy customer",  "body": "\"A short quote about what they loved and why they'd recommend us.\""},
                {"heading": "— Happy customer",  "body": "\"A short quote about what they loved and why they'd recommend us.\""},
            ]}},
            {"block_type": "content_2col", "block_data": {"columns": [
                {"heading": "— Happy customer",  "body": "\"A short quote about what they loved and why they'd recommend us.\""},
                {"heading": "— Happy customer",  "body": "\"A short quote about what they loved and why they'd recommend us.\""},
            ]}},
        ],
    },
    {
        "key": "core_events",
        "section": "Content",
        "name": "Events Calendar",
        "slug": "events",
        "page_title": "Upcoming Events",
        "business_type_ids": None,
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Upcoming Events",
                "subtext": "Classes, workshops, open houses, and special dates.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content", "block_data": {
                "heading": "This season",
                "body": "List upcoming events with dates, times, and how to attend. Link to registration where applicable.",
            }},
        ],
    },

    # ── Farm / Ranch (BT=8) ───────────────────────────────────────────────
    {
        "key": "farm_our_animals",
        "section": "Farm",
        "name": "Our Animals",
        "slug": "our-animals",
        "page_title": "Our Animals",
        "business_type_ids": [BT_FARM_RANCH],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Our Animals",
                "subtext": "The breeds we raise and why we chose them.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content", "block_data": {
                "heading": "Our herd / flock",
                "body": "Introduce your animals — breed, temperament, how they fit your operation, and what you sell.",
            }},
        ],
    },
    {
        "key": "farm_our_products",
        "section": "Farm",
        "name": "Our Products",
        "slug": "products",
        "page_title": "What We Sell",
        "business_type_ids": [BT_FARM_RANCH],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "What We Sell",
                "subtext": "From our farm to your table.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content_3col", "block_data": {"columns": [
                {"heading": "Meat",      "body": "Cuts available, ordering, and pickup or delivery options."},
                {"heading": "Eggs & dairy", "body": "Availability by season and how to place a standing order."},
                {"heading": "Fiber & hides", "body": "Raw or processed — sold by request."},
            ]}},
        ],
    },
    {
        "key": "farm_tours",
        "section": "Farm",
        "name": "Farm Tours",
        "slug": "tours",
        "page_title": "Farm Tours",
        "business_type_ids": [BT_FARM_RANCH],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Visit the Farm",
                "subtext": "See where your food comes from.",
                "cta_text": "Book a Tour", "cta_link": "#book",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content_2col", "block_data": {"columns": [
                {"heading": "What to expect",  "body": "Tour length, what you'll see, and what to wear."},
                {"heading": "Booking",         "body": "Available days, group sizes, and pricing."},
            ]}},
            {"block_type": "contact", "block_data": {
                "heading": "Request a tour",
                "body": "Send us a date and group size and we'll confirm availability.",
            }},
        ],
    },
    {
        "key": "farm_csa",
        "section": "Farm",
        "name": "CSA / Subscription",
        "slug": "csa",
        "page_title": "CSA Membership",
        "business_type_ids": [BT_FARM_RANCH],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Join Our CSA",
                "subtext": "A season of fresh food, delivered on a schedule.",
                "cta_text": "Sign Up", "cta_link": "#signup",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content_3col", "block_data": {"columns": [
                {"heading": "Share sizes", "body": "Small, medium, or large — pick what fits your household."},
                {"heading": "Pickup",      "body": "Pickup locations, days, and times."},
                {"heading": "What's included", "body": "Seasonal rotation of what we're growing or raising."},
            ]}},
        ],
    },

    # ── Restaurant (BT=9) ─────────────────────────────────────────────────
    {
        "key": "restaurant_menu",
        "section": "Restaurant",
        "name": "Menu",
        "slug": "menu",
        "page_title": "Our Menu",
        "business_type_ids": [BT_RESTAURANT],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Our Menu",
                "subtext": "Seasonal, sourced locally where we can.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content_2col", "block_data": {"columns": [
                {"heading": "Starters",  "body": "Dish — short description. Price."},
                {"heading": "Entrées",   "body": "Dish — short description. Price."},
            ]}},
            {"block_type": "content_2col", "block_data": {"columns": [
                {"heading": "Sides",     "body": "Dish — short description. Price."},
                {"heading": "Desserts",  "body": "Dish — short description. Price."},
            ]}},
        ],
    },
    {
        "key": "restaurant_hours_location",
        "section": "Restaurant",
        "name": "Hours & Location",
        "slug": "hours",
        "page_title": "Hours & Location",
        "business_type_ids": [BT_RESTAURANT],
        "default_blocks": [
            {"block_type": "hours_of_operation", "block_data": {
                "heading": "Hours", "intro_body": "", "timezone": "",
                "hours": [
                    {"day": "Monday",    "open": "",      "close": "",       "closed": True,  "notes": ""},
                    {"day": "Tuesday",   "open": "11:00", "close": "9:00pm", "closed": False, "notes": ""},
                    {"day": "Wednesday", "open": "11:00", "close": "9:00pm", "closed": False, "notes": ""},
                    {"day": "Thursday",  "open": "11:00", "close": "9:00pm", "closed": False, "notes": ""},
                    {"day": "Friday",    "open": "11:00", "close": "10:00pm","closed": False, "notes": ""},
                    {"day": "Saturday",  "open": "10:00", "close": "10:00pm","closed": False, "notes": "Brunch till 2pm"},
                    {"day": "Sunday",    "open": "10:00", "close": "8:00pm", "closed": False, "notes": ""},
                ],
            }},
            {"block_type": "map_location", "block_data": {
                "heading": "Location",
                "address": "",
                "embed_url": "",
                "height": 320,
            }},
            {"block_type": "contact", "block_data": {
                "heading": "Reservations",
                "body": "Call, email, or reserve online.",
            }},
        ],
    },

    # ── Fiber Mill (BT=18) ────────────────────────────────────────────────
    {
        "key": "fibermill_services",
        "section": "Fiber Mill",
        "name": "Mill Services",
        "slug": "services",
        "page_title": "Mill Services",
        "business_type_ids": [BT_FIBER_MILL],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Mill Services",
                "subtext": "From raw fleece to finished yarn.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content_3col", "block_data": {"columns": [
                {"heading": "Washing & picking", "body": "Scoured and opened, ready for carding."},
                {"heading": "Carding & roving",  "body": "Batt or roving, your choice of weight."},
                {"heading": "Spinning",          "body": "Singles, plied, or custom blends."},
            ]}},
            {"block_type": "fee_schedule", "block_data": {
                "heading": "Service pricing",
                "rows": [
                    {"item": "Wash",     "amount": "$/lb", "notes": "Minimum batch size may apply."},
                    {"item": "Card",     "amount": "$/lb", "notes": ""},
                    {"item": "Spin",     "amount": "$/lb", "notes": "Singles or plied."},
                ],
            }},
        ],
    },
    {
        "key": "fibermill_process",
        "section": "Fiber Mill",
        "name": "How It Works",
        "slug": "process",
        "page_title": "Our Process",
        "business_type_ids": [BT_FIBER_MILL],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "From Fleece to Yarn",
                "subtext": "A walkthrough of what happens when you send us your fiber.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content_3col", "block_data": {"columns": [
                {"heading": "1. Intake",   "body": "Weigh, inspect, and log your fleece."},
                {"heading": "2. Processing", "body": "Wash, card, spin — tracked at every step."},
                {"heading": "3. Return",   "body": "Finished product shipped back or ready for pickup."},
            ]}},
        ],
    },

    # ── Farmers Market (BT=29) ────────────────────────────────────────────
    {
        "key": "market_vendors",
        "section": "Market",
        "name": "Our Vendors",
        "slug": "vendors",
        "page_title": "Market Vendors",
        "business_type_ids": [BT_FARMERS_MARKET],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Meet Our Vendors",
                "subtext": "The farms, artisans, and makers who sell at our market.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content", "block_data": {
                "heading": "This season's vendors",
                "body": "Add vendor listings, or embed the vendor directory widget.",
            }},
        ],
    },
    {
        "key": "market_info",
        "section": "Market",
        "name": "Market Info",
        "slug": "market-info",
        "page_title": "Market Info",
        "business_type_ids": [BT_FARMERS_MARKET],
        "default_blocks": [
            {"block_type": "content_2col", "block_data": {"columns": [
                {"heading": "When & where", "body": "Season, day(s) of the week, hours, and location."},
                {"heading": "What to expect", "body": "Parking, pets, payment types accepted, and accessibility."},
            ]}},
            {"block_type": "content_2col", "block_data": {"columns": [
                {"heading": "Become a vendor", "body": "Application process, stall fees, and product standards."},
                {"heading": "Sponsor the market", "body": "How local businesses can support the market."},
            ]}},
        ],
    },

    # ── Artisan Food Producer (BT=11) ─────────────────────────────────────
    {
        "key": "artisan_products",
        "section": "Artisan Food",
        "name": "Our Products",
        "slug": "products",
        "page_title": "Our Products",
        "business_type_ids": [BT_ARTISAN_FOOD],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Handcrafted, Small Batch",
                "subtext": "What we make and how we make it.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content_3col", "block_data": {"columns": [
                {"heading": "Signature items", "body": "Our most-loved products — short description, ingredients, price."},
                {"heading": "Seasonal",        "body": "What's available only at certain times of year."},
                {"heading": "Custom orders",   "body": "Wedding cakes, wholesale, gift baskets — how to request."},
            ]}},
        ],
    },
    {
        "key": "artisan_where_to_buy",
        "section": "Artisan Food",
        "name": "Where to Buy",
        "slug": "where-to-buy",
        "business_type_ids": [BT_ARTISAN_FOOD],
        "default_blocks": [
            {"block_type": "content", "block_data": {
                "heading": "Where to find us",
                "body": "Markets, stores, and restaurants that carry our products — plus our online shop.",
            }},
            {"block_type": "links", "block_data": {
                "heading": "Retail partners",
                "links": [
                    {"label": "Local Co-op",     "url": "#"},
                    {"label": "Farmers Market",  "url": "#"},
                    {"label": "Online Shop",     "url": "/store"},
                ],
            }},
        ],
    },

    # ── Winery / Vineyard (BT=33, 34) ─────────────────────────────────────
    {
        "key": "winery_wines",
        "section": "Winery",
        "name": "Our Wines",
        "slug": "wines",
        "page_title": "Our Wines",
        "business_type_ids": [BT_WINERY, BT_VINEYARD],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Our Wines",
                "subtext": "Varietals, vintages, and tasting notes.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content_2col", "block_data": {"columns": [
                {"heading": "Whites",  "body": "Varietal — vintage. Tasting notes."},
                {"heading": "Reds",    "body": "Varietal — vintage. Tasting notes."},
            ]}},
            {"block_type": "content_2col", "block_data": {"columns": [
                {"heading": "Rosé",     "body": "Varietal — vintage. Tasting notes."},
                {"heading": "Reserve",  "body": "Limited-release and library wines."},
            ]}},
        ],
    },
    {
        "key": "winery_tastings",
        "section": "Winery",
        "name": "Tastings & Events",
        "slug": "tastings",
        "page_title": "Tastings & Events",
        "business_type_ids": [BT_WINERY, BT_VINEYARD],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Come for a Tasting",
                "subtext": "Walk-ins welcome, reservations recommended on weekends.",
                "cta_text": "Book a Tasting", "cta_link": "#book",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content_2col", "block_data": {"columns": [
                {"heading": "Tasting flights",   "body": "Number of pours, price, and what's included."},
                {"heading": "Private events",    "body": "Weddings, corporate, and group tastings — how to book."},
            ]}},
            {"block_type": "contact", "block_data": {
                "heading": "Reserve your tasting",
                "body": "Tell us your party size and date, and we'll confirm.",
            }},
        ],
    },

    # ── Cooperatives (Food/Fiber Co-ops) ──────────────────────────────────
    {
        "key": "coop_join",
        "section": "Cooperative",
        "name": "Become a Member-Owner",
        "slug": "join",
        "page_title": "Become a Member-Owner",
        "business_type_ids": [BT_FOOD_COOP, BT_FIBER_COOP],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Become a Member-Owner",
                "subtext": "Own a share of your local co-op — discounts, voting rights, and a say in what we carry.",
                "cta_text": "Buy a Share", "cta_link": "#share",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content_3col", "block_data": {"columns": [
                {"heading": "Member discounts", "body": "Regular discount days and sale pricing for owners."},
                {"heading": "Patronage dividends", "body": "Profits returned to owners based on yearly purchases."},
                {"heading": "Democratic ownership", "body": "One member, one vote — elect the board and shape direction."},
            ]}},
        ],
    },
    {
        "key": "coop_board",
        "section": "Cooperative",
        "name": "Board of Directors",
        "slug": "board",
        "business_type_ids": [BT_FOOD_COOP, BT_FIBER_COOP],
        "default_blocks": [
            {"block_type": "content", "block_data": {
                "heading": "Board of Directors",
                "body": "Elected by member-owners to set policy and oversee the co-op's general manager.",
            }},
            {"block_type": "content_3col", "block_data": {"columns": [
                {"heading": "Director — Chair", "body": "Name, term, committee assignments."},
                {"heading": "Director", "body": "Name, term, committee assignments."},
                {"heading": "Director", "body": "Name, term, committee assignments."},
            ]}},
        ],
    },
    {
        "key": "coop_patronage",
        "section": "Cooperative",
        "name": "Patronage & Returns",
        "slug": "patronage",
        "business_type_ids": [BT_FOOD_COOP, BT_FIBER_COOP],
        "default_blocks": [
            {"block_type": "content", "block_data": {
                "heading": "How Patronage Works",
                "body": "When the co-op has a profitable year, a share of those profits is returned to member-owners based on how much they purchased.",
            }},
            {"block_type": "content_2col", "block_data": {"columns": [
                {"heading": "Calculating your share", "body": "Your dividend is proportional to your annual spending at the co-op."},
                {"heading": "Distribution", "body": "Part is paid out as cash; part is retained as equity to keep the co-op strong."},
            ]}},
        ],
    },

    # ── Veterinarian (BT=17) ──────────────────────────────────────────────
    {
        "key": "vet_services",
        "section": "Veterinary",
        "name": "Our Services",
        "slug": "services",
        "page_title": "Veterinary Services",
        "business_type_ids": [BT_VETERINARIAN],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Compassionate Care for Your Animals",
                "subtext": "Preventive care, diagnostics, surgery, and emergency services.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content_3col", "block_data": {"columns": [
                {"heading": "Wellness & prevention", "body": "Vaccines, dental care, nutrition counseling, and annual exams."},
                {"heading": "Diagnostics & surgery", "body": "In-house lab, imaging, and soft-tissue surgery."},
                {"heading": "Urgent care",           "body": "Same-day sick visits during business hours."},
            ]}},
        ],
    },
    {
        "key": "vet_team",
        "section": "Veterinary",
        "name": "Meet the Vets",
        "slug": "our-team",
        "business_type_ids": [BT_VETERINARIAN],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Meet Your Veterinary Team",
                "subtext": "Our veterinarians, technicians, and support staff.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content_3col", "block_data": {"columns": [
                {"heading": "Dr. Name, DVM", "body": "Credentials, special interests, and years in practice."},
                {"heading": "Dr. Name, DVM", "body": "Credentials, special interests, and years in practice."},
                {"heading": "Support staff",  "body": "Our licensed technicians and client-care team."},
            ]}},
        ],
    },
    {
        "key": "vet_emergency",
        "section": "Veterinary",
        "name": "After-Hours & Emergency",
        "slug": "emergency",
        "business_type_ids": [BT_VETERINARIAN],
        "default_blocks": [
            {"block_type": "content", "block_data": {
                "heading": "After-Hours Emergencies",
                "body": "For life-threatening emergencies outside our regular hours, please contact the emergency clinic below. Our on-call line is for established patients only.",
            }},
            {"block_type": "content_2col", "block_data": {"columns": [
                {"heading": "Regional emergency clinic", "body": "Name, address, phone — open 24/7."},
                {"heading": "Poison control",            "body": "ASPCA Animal Poison Control: (888) 426-4435 (fee applies)."},
            ]}},
        ],
    },

    # ── University / Extension (BT=27) ────────────────────────────────────
    {
        "key": "uni_programs",
        "section": "Academic",
        "name": "Programs & Majors",
        "slug": "programs",
        "page_title": "Programs & Majors",
        "business_type_ids": [BT_UNIVERSITY],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Programs & Majors",
                "subtext": "Undergraduate, graduate, and certificate programs in agriculture and related fields.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content_3col", "block_data": {"columns": [
                {"heading": "Animal Science",     "body": "Breeding, nutrition, welfare, and management."},
                {"heading": "Crop & Soil Science", "body": "Agronomy, soil health, and sustainable production."},
                {"heading": "Agribusiness",       "body": "Farm management, marketing, and policy."},
            ]}},
        ],
    },
    {
        "key": "uni_extension",
        "section": "Academic",
        "name": "Extension & Outreach",
        "slug": "extension",
        "business_type_ids": [BT_UNIVERSITY],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Cooperative Extension",
                "subtext": "Bringing research-based knowledge to farmers, ranchers, and communities.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content_2col", "block_data": {"columns": [
                {"heading": "For producers",  "body": "Workshops, field days, and one-on-one consultation."},
                {"heading": "For communities", "body": "4-H, Master Gardener, and family & consumer programs."},
            ]}},
        ],
    },
    {
        "key": "uni_research",
        "section": "Academic",
        "name": "Research",
        "slug": "research",
        "business_type_ids": [BT_UNIVERSITY],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Research",
                "subtext": "Applied agricultural research serving our region.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content_3col", "block_data": {"columns": [
                {"heading": "Current projects", "body": "Funded research active this year."},
                {"heading": "Publications",     "body": "Recent papers, bulletins, and extension publications."},
                {"heading": "Collaborate",      "body": "Industry partnerships and contract research."},
            ]}},
        ],
    },

    # ── Fishery / Fishermen (BT=22, 23) ──────────────────────────────────
    {
        "key": "fishery_catch",
        "section": "Fishery",
        "name": "What We Catch",
        "slug": "our-catch",
        "page_title": "Our Catch",
        "business_type_ids": [BT_FISHERY, BT_FISHERMEN],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Dock to Door",
                "subtext": "Wild-caught seafood, landed by our boats and sold direct.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content_3col", "block_data": {"columns": [
                {"heading": "Finfish",    "body": "Species we catch, when they're in season, and how to order."},
                {"heading": "Shellfish",  "body": "Oysters, clams, mussels — by the dozen or the bushel."},
                {"heading": "Specialty",  "body": "Smoked, dried, or specialty preparations available by request."},
            ]}},
        ],
    },
    {
        "key": "fishery_csf",
        "section": "Fishery",
        "name": "Community Supported Fishery",
        "slug": "csf",
        "page_title": "CSF Subscription",
        "business_type_ids": [BT_FISHERY, BT_FISHERMEN],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Community Supported Fishery",
                "subtext": "A subscription share of what our boats bring in — delivered fresh each week.",
                "cta_text": "Sign Up", "cta_link": "#signup",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content_2col", "block_data": {"columns": [
                {"heading": "How it works",  "body": "You pay up-front for a season. Each week you get a share of the catch at a pickup location near you."},
                {"heading": "Share sizes",   "body": "Single, family, or restaurant — different sizes and delivery cadences."},
            ]}},
        ],
    },

    # ── Retailer / Grocery (BT=24, 26) ────────────────────────────────────
    {
        "key": "retail_departments",
        "section": "Retail",
        "name": "Departments",
        "slug": "departments",
        "page_title": "Shop by Department",
        "business_type_ids": [BT_RETAILER, BT_GROCERY],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Shop by Department",
                "subtext": "A tour of what you'll find on our shelves.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content_3col", "block_data": {"columns": [
                {"heading": "Produce",  "body": "Local and seasonal picks, plus staples year-round."},
                {"heading": "Meat & dairy", "body": "Sourced from farms we know by name."},
                {"heading": "Bulk & pantry", "body": "Grains, flours, spices, and pantry basics."},
            ]}},
        ],
    },
    {
        "key": "retail_locations",
        "section": "Retail",
        "name": "Store Locations",
        "slug": "locations",
        "business_type_ids": [BT_RETAILER, BT_GROCERY],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Visit a Store",
                "subtext": "Addresses, hours, and directions.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content_2col", "block_data": {"columns": [
                {"heading": "Main Store",   "body": "Address • Phone • Hours • Parking notes"},
                {"heading": "Second Store", "body": "Address • Phone • Hours • Parking notes"},
            ]}},
        ],
    },

    # ── Herb & Tea Producer (BT=31) ───────────────────────────────────────
    {
        "key": "herbtea_products",
        "section": "Herb & Tea",
        "name": "Our Blends",
        "slug": "blends",
        "page_title": "Our Blends",
        "business_type_ids": [BT_HERB_TEA],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Small-Batch Blends",
                "subtext": "Grown, dried, and blended by hand.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content_3col", "block_data": {"columns": [
                {"heading": "Herbal blends", "body": "Caffeine-free infusions crafted for flavor and wellness."},
                {"heading": "Tea blends",    "body": "Black, green, and white teas — plain or blended with herbs."},
                {"heading": "Tisanes & tonics", "body": "Seasonal blends and functional tonics."},
            ]}},
        ],
    },
    {
        "key": "herbtea_brewing",
        "section": "Herb & Tea",
        "name": "Brewing Guide",
        "slug": "brewing",
        "business_type_ids": [BT_HERB_TEA],
        "default_blocks": [
            {"block_type": "content", "block_data": {
                "heading": "How to Brew",
                "body": "Small details make a big difference — water temperature, steep time, and leaf-to-water ratio all matter.",
            }},
            {"block_type": "content_3col", "block_data": {"columns": [
                {"heading": "Green tea",  "body": "170–180°F • 2 min • 1 tsp / 8 oz."},
                {"heading": "Black tea",  "body": "200–212°F • 3–5 min • 1 tsp / 8 oz."},
                {"heading": "Herbal",     "body": "212°F • 5–10 min • 1–2 tsp / 8 oz."},
            ]}},
        ],
    },

    # ── Crafters Organization (BT=15) ─────────────────────────────────────
    {
        "key": "crafters_shows",
        "section": "Crafters",
        "name": "Guild Shows & Sales",
        "slug": "shows",
        "business_type_ids": [BT_CRAFTERS_ORG],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Shows & Sales",
                "subtext": "Where to find our members' work throughout the year.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content_2col", "block_data": {"columns": [
                {"heading": "Upcoming shows",  "body": "Dates, locations, and how to attend or apply as a vendor."},
                {"heading": "Juried sales",    "body": "Jury process, standards, and application windows."},
            ]}},
        ],
    },

    # ── Additional universal content (Careers, Newsletter, Mission) ───────
    {
        "key": "core_careers",
        "section": "Core",
        "name": "Careers",
        "slug": "careers",
        "page_title": "Join Our Team",
        "business_type_ids": None,
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Join Our Team",
                "subtext": "We're always looking for good people.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content", "block_data": {
                "heading": "Open positions",
                "body": "List current openings — title, department, and a short description. Link to the application or email.",
            }},
            {"block_type": "content_2col", "block_data": {"columns": [
                {"heading": "What we value",  "body": "The qualities and work ethic we look for in teammates."},
                {"heading": "Benefits",       "body": "What you get when you join us beyond salary."},
            ]}},
        ],
    },
    {
        "key": "core_newsletter_signup",
        "section": "Core",
        "name": "Newsletter Signup",
        "slug": "newsletter",
        "page_title": "Sign Up for Our Newsletter",
        "business_type_ids": None,
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Stay in Touch",
                "subtext": "News, tips, and special offers — in your inbox, not your junk folder.",
                "cta_text": "Sign Me Up", "cta_link": "#signup",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content_2col", "block_data": {"columns": [
                {"heading": "What to expect", "body": "How often we send, what's inside, and how easy it is to unsubscribe."},
                {"heading": "Your privacy",   "body": "We don't sell or share your email. One-click unsubscribe, always."},
            ]}},
        ],
    },
    {
        "key": "core_sustainability",
        "section": "Core",
        "name": "Sustainability / Mission",
        "slug": "sustainability",
        "page_title": "Our Mission",
        "business_type_ids": None,
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Our Mission",
                "subtext": "Why we do what we do, and how we measure our impact.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content", "block_data": {
                "heading": "What drives us",
                "body": "Our mission statement and the principles behind our work.",
            }},
            {"block_type": "content_3col", "block_data": {"columns": [
                {"heading": "People",    "body": "How we treat our team, partners, and community."},
                {"heading": "Planet",    "body": "Our environmental commitments and practices."},
                {"heading": "Progress",  "body": "How we measure and report on our impact."},
            ]}},
        ],
    },

    # ── Food Hub (BT=10) ─────────────────────────────────────────────────
    {
        "key": "foodhub_producers",
        "section": "Food Hub",
        "name": "Our Producers",
        "slug": "producers",
        "page_title": "Our Producer Network",
        "business_type_ids": [BT_FOOD_HUB],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "The Farms Behind Our Food",
                "subtext": "We aggregate from dozens of local producers so wholesale buyers can source regionally with one purchase order.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content_3col", "block_data": {"columns": [
                {"heading": "Produce growers",   "body": "Fruit, vegetable, and herb farms in our sourcing region."},
                {"heading": "Livestock farms",   "body": "Meat, poultry, and dairy producers we work with."},
                {"heading": "Value-added",       "body": "Artisan producers turning raw ingredients into pantry staples."},
            ]}},
        ],
    },
    {
        "key": "foodhub_buyers",
        "section": "Food Hub",
        "name": "For Wholesale Buyers",
        "slug": "buyers",
        "business_type_ids": [BT_FOOD_HUB],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Wholesale Sourcing Made Simple",
                "subtext": "One invoice, one delivery, regional food — for restaurants, schools, hospitals, and retail.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content_2col", "block_data": {"columns": [
                {"heading": "How to order",  "body": "Catalog access, ordering windows, and delivery schedule."},
                {"heading": "Pricing & terms", "body": "Minimums, payment terms, and contract options."},
            ]}},
        ],
    },

    # ── Meat Wholesaler (BT=19) ──────────────────────────────────────────
    {
        "key": "meatwholesale_cuts",
        "section": "Meat Wholesale",
        "name": "Cut Sheet & Availability",
        "slug": "cuts",
        "business_type_ids": [BT_MEAT_WHOLESALER],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Cuts & Availability",
                "subtext": "Primals, subprimals, and retail cuts — spec sheets available on request.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content_3col", "block_data": {"columns": [
                {"heading": "Beef",    "body": "Grass-fed, grain-finished, and dry-aged options."},
                {"heading": "Pork",    "body": "Heritage and commodity cuts; whole hogs available."},
                {"heading": "Poultry", "body": "Whole birds and portioned cuts."},
            ]}},
        ],
    },
    {
        "key": "meatwholesale_accounts",
        "section": "Meat Wholesale",
        "name": "Wholesale Accounts",
        "slug": "accounts",
        "business_type_ids": [BT_MEAT_WHOLESALER],
        "default_blocks": [
            {"block_type": "content", "block_data": {
                "heading": "Open a Wholesale Account",
                "body": "Application process, references, and credit terms. Accounts typically open within 5 business days.",
            }},
            {"block_type": "contact", "block_data": {
                "heading": "Request an application",
                "body": "Tell us about your operation and we'll send the right paperwork.",
            }},
        ],
    },

    # ── Manufacturer (BT=16) ─────────────────────────────────────────────
    {
        "key": "mfg_capabilities",
        "section": "Manufacturing",
        "name": "Capabilities",
        "slug": "capabilities",
        "page_title": "Manufacturing Capabilities",
        "business_type_ids": [BT_MANUFACTURER],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "What We Make",
                "subtext": "Equipment, tolerances, and materials we work with.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content_3col", "block_data": {"columns": [
                {"heading": "Equipment",   "body": "Machines, tonnage, envelope sizes, and quality systems."},
                {"heading": "Materials",   "body": "Metals, plastics, composites, or food-safe grades we handle."},
                {"heading": "Certifications", "body": "ISO, AS, FDA, SQF — whichever apply to your industry."},
            ]}},
        ],
    },
    {
        "key": "mfg_request_quote",
        "section": "Manufacturing",
        "name": "Request a Quote",
        "slug": "request-quote",
        "business_type_ids": [BT_MANUFACTURER],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Request a Quote",
                "subtext": "Send drawings or specs and we'll get back to you within 2 business days.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "contact", "block_data": {
                "heading": "Quote request",
                "body": "Include part description, quantity, target price, and timeline. Attach drawings if you have them.",
            }},
        ],
    },

    # ── Service Provider (BT=20) ─────────────────────────────────────────
    {
        "key": "svc_what_we_do",
        "section": "Service",
        "name": "What We Do",
        "slug": "what-we-do",
        "business_type_ids": [BT_SERVICE_PROVIDER],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "What We Do",
                "subtext": "The services we offer and who we help.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content_3col", "block_data": {"columns": [
                {"heading": "Core service",       "body": "What this is and the typical customer."},
                {"heading": "Premium service",    "body": "What's included and who it's best for."},
                {"heading": "Custom engagements", "body": "How we scope work that doesn't fit a package."},
            ]}},
        ],
    },
    {
        "key": "svc_process",
        "section": "Service",
        "name": "Our Process",
        "slug": "process",
        "business_type_ids": [BT_SERVICE_PROVIDER],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "How We Work",
                "subtext": "From first call to final delivery.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content_3col", "block_data": {"columns": [
                {"heading": "1. Discovery",  "body": "We learn about your goals, constraints, and success criteria."},
                {"heading": "2. Proposal",   "body": "A written scope of work with timeline, deliverables, and pricing."},
                {"heading": "3. Delivery",   "body": "Regular check-ins, milestones, and a clean hand-off."},
            ]}},
        ],
    },

    # ── Marina (BT=21) ───────────────────────────────────────────────────
    {
        "key": "marina_slip_rentals",
        "section": "Marina",
        "name": "Slip Rentals",
        "slug": "slips",
        "business_type_ids": [BT_MARINA],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Slip Rentals",
                "subtext": "Seasonal and transient slips — power, water, and pump-out included.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content_2col", "block_data": {"columns": [
                {"heading": "Seasonal",   "body": "Rate, deposit, and what the season runs. Waitlist if applicable."},
                {"heading": "Transient",  "body": "Nightly and weekly rates, check-in process, and reservation policy."},
            ]}},
            {"block_type": "fee_schedule", "block_data": {
                "heading": "Slip pricing",
                "rows": [
                    {"item": "20 ft slip",        "amount": "$—/ft", "notes": "Seasonal rate."},
                    {"item": "30 ft slip",        "amount": "$—/ft", "notes": "Seasonal rate."},
                    {"item": "40 ft slip",        "amount": "$—/ft", "notes": "Seasonal rate."},
                    {"item": "Transient (daily)", "amount": "$—",    "notes": "Plus $0.20/ft."},
                ],
            }},
        ],
    },
    {
        "key": "marina_services",
        "section": "Marina",
        "name": "Marina Services",
        "slug": "services",
        "business_type_ids": [BT_MARINA],
        "default_blocks": [
            {"block_type": "content_3col", "block_data": {"columns": [
                {"heading": "Fuel & pump-out",   "body": "Gas, diesel, and pump-out hours and pricing."},
                {"heading": "Service & repairs", "body": "Mechanical, detailing, and winterization."},
                {"heading": "Storage",           "body": "Dry stack and winter inside/outside storage."},
            ]}},
        ],
    },

    # ── Transporter (BT=32) ──────────────────────────────────────────────
    {
        "key": "transport_services",
        "section": "Transport",
        "name": "Shipping Services",
        "slug": "services",
        "business_type_ids": [BT_TRANSPORTER],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Livestock & Freight Transport",
                "subtext": "Safe, compliant, and on time.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content_3col", "block_data": {"columns": [
                {"heading": "Livestock",       "body": "Single-animal to full-trailer loads. Climate-controlled options available."},
                {"heading": "Refrigerated",    "body": "Reefer freight for meat, dairy, and produce."},
                {"heading": "Equipment",       "body": "Heavy equipment, hay, and agricultural inputs."},
            ]}},
        ],
    },
    {
        "key": "transport_request",
        "section": "Transport",
        "name": "Request Transport",
        "slug": "request-transport",
        "business_type_ids": [BT_TRANSPORTER],
        "default_blocks": [
            {"block_type": "contact", "block_data": {
                "heading": "Request a quote",
                "body": "Origin, destination, animal or freight type, count/weight, pickup window, and any special requirements.",
            }},
        ],
    },

    # ── Real Estate Agent (BT=30) ────────────────────────────────────────
    {
        "key": "realestate_listings",
        "section": "Real Estate",
        "name": "Current Listings",
        "slug": "listings",
        "business_type_ids": [BT_REAL_ESTATE],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Current Listings",
                "subtext": "Farms, ranches, and rural properties.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content", "block_data": {
                "heading": "Featured properties",
                "body": "Add property cards with photos, price, acreage, and a link to the full listing.",
            }},
        ],
    },
    {
        "key": "realestate_buyers",
        "section": "Real Estate",
        "name": "For Buyers",
        "slug": "buyers",
        "business_type_ids": [BT_REAL_ESTATE],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Looking for Land?",
                "subtext": "We help buyers find farms, pasture, timber, and recreational property.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content_2col", "block_data": {"columns": [
                {"heading": "Buyer's guide",  "body": "Water rights, zoning, ag assessments — what to know before you make an offer."},
                {"heading": "Search tools",   "body": "Saved searches, listing alerts, and pre-market opportunities."},
            ]}},
        ],
    },

    # ── Hunger Relief Organization (BT=35) ───────────────────────────────
    {
        "key": "hunger_get_help",
        "section": "Hunger Relief",
        "name": "Get Food Assistance",
        "slug": "get-help",
        "page_title": "Get Food Assistance",
        "business_type_ids": [BT_HUNGER_RELIEF],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Get Food Assistance",
                "subtext": "No one should go hungry. Here's how to access our pantry and programs.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content_2col", "block_data": {"columns": [
                {"heading": "Pantry hours",  "body": "Days, times, and location. No appointment needed."},
                {"heading": "What to bring", "body": "ID or proof of address if you have it; not required for first-time visitors."},
            ]}},
            {"block_type": "content", "block_data": {
                "heading": "Other programs",
                "body": "Mobile pantry, senior boxes, weekend backpacks for kids, and holiday meal distributions.",
            }},
        ],
    },
    {
        "key": "hunger_donate",
        "section": "Hunger Relief",
        "name": "Donate & Volunteer",
        "slug": "donate",
        "business_type_ids": [BT_HUNGER_RELIEF],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Help Us Feed Neighbors",
                "subtext": "Donate food, donate funds, or volunteer a shift.",
                "cta_text": "Donate Now", "cta_link": "#donate",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content_3col", "block_data": {"columns": [
                {"heading": "Food drives",     "body": "Most-needed items and drop-off hours."},
                {"heading": "Financial gifts", "body": "Every dollar is matched and stretches further than retail."},
                {"heading": "Volunteer",       "body": "Shift sign-up, group opportunities, and youth involvement."},
            ]}},
        ],
    },

    # ── Business Resources (BT=28) ───────────────────────────────────────
    {
        "key": "resources_programs",
        "section": "Resources",
        "name": "Programs & Services",
        "slug": "programs",
        "business_type_ids": [BT_BUSINESS_RESOURCES],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Programs for Agricultural Businesses",
                "subtext": "Grants, loans, training, and one-on-one technical assistance.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content_3col", "block_data": {"columns": [
                {"heading": "Financial programs", "body": "Grants, cost-share, and revolving loan funds."},
                {"heading": "Training",           "body": "Workshops, webinars, and certificate programs."},
                {"heading": "Consulting",         "body": "Business-plan support, financial review, and market research."},
            ]}},
        ],
    },
    {
        "key": "resources_library",
        "section": "Resources",
        "name": "Resource Library",
        "slug": "library",
        "business_type_ids": [BT_BUSINESS_RESOURCES],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Resource Library",
                "subtext": "Templates, guides, and research — free for the agricultural community.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "links", "block_data": {
                "heading": "Browse by topic",
                "links": [
                    {"label": "Business planning", "url": "#"},
                    {"label": "Marketing & branding", "url": "#"},
                    {"label": "Finance & accounting", "url": "#"},
                    {"label": "Policy & regulation",  "url": "#"},
                ],
            }},
        ],
    },

    # ── Wave 7: Additional Association content ───────────────────────────
    # (assoc_bylaws and assoc_chapters already exist earlier in the catalog)
    {
        "key": "assoc_annual_report",
        "section": "About",
        "name": "Annual Report",
        "slug": "annual-report",
        "business_type_ids": [BT_ASSOCIATION],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Annual Report",
                "subtext": "A year in review — finances, programs, and progress against our strategic plan.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content_3col", "block_data": {"columns": [
                {"heading": "Financials",   "body": "Revenue, expenses, and audited statements."},
                {"heading": "Program highlights", "body": "What we accomplished this year."},
                {"heading": "Looking ahead", "body": "Strategic priorities for the year ahead."},
            ]}},
        ],
    },
    {
        "key": "assoc_policy_positions",
        "section": "Advocacy",
        "name": "Policy Positions",
        "slug": "policy-positions",
        "business_type_ids": [BT_ASSOCIATION],
        "default_blocks": [
            {"block_type": "content", "block_data": {
                "heading": "Our Policy Positions",
                "body": "Where the association stands on issues affecting members. Positions are set by the board after member input.",
            }},
            {"block_type": "content_2col", "block_data": {"columns": [
                {"heading": "Current priorities",  "body": "The issues we're actively working on this session."},
                {"heading": "How positions are set", "body": "Member comment windows, board review, and publication."},
            ]}},
        ],
    },
    {
        "key": "assoc_industry_stats",
        "section": "Industry",
        "name": "Industry Statistics",
        "slug": "industry-stats",
        "business_type_ids": [BT_ASSOCIATION],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Industry Statistics",
                "subtext": "Registration counts, breed population trends, and market data.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content_3col", "block_data": {"columns": [
                {"heading": "Registration trends", "body": "Annual registrations, by region and class."},
                {"heading": "Population",          "body": "Census data and inventory snapshots."},
                {"heading": "Market data",         "body": "Average prices, top-performing bloodlines, and sale results."},
            ]}},
        ],
    },
    {
        "key": "assoc_affiliates",
        "section": "Membership",
        "name": "Affiliates & Partners",
        "slug": "affiliates",
        "business_type_ids": [BT_ASSOCIATION],
        "default_blocks": [
            {"block_type": "content", "block_data": {
                "heading": "Affiliates & Partners",
                "body": "Organizations we work with — sister associations, industry partners, and discount providers for members.",
            }},
            {"block_type": "links", "block_data": {
                "heading": "Partner organizations",
                "links": [
                    {"label": "Sister association",     "url": "#"},
                    {"label": "Industry publication",   "url": "#"},
                    {"label": "Insurance partner",      "url": "#"},
                ],
            }},
        ],
    },
    {
        "key": "assoc_awards_hall_of_fame",
        "section": "Awards",
        "name": "Hall of Fame",
        "slug": "hall-of-fame",
        "business_type_ids": [BT_ASSOCIATION],
        "default_blocks": [
            {"block_type": "hero", "block_data": {
                "headline": "Hall of Fame",
                "subtext": "Breeders, animals, and advocates whose contributions shaped the breed.",
                "overlay": True, "align": "center",
            }},
            {"block_type": "content_2col", "block_data": {"columns": [
                {"heading": "Breeder inductees", "body": "Individuals recognized for lifetime contributions."},
                {"heading": "Animal inductees",  "body": "Foundation animals and historic champions."},
            ]}},
            {"block_type": "content", "block_data": {
                "heading": "Nominate for induction",
                "body": "Nomination criteria, timeline, and selection committee process.",
            }},
        ],
    },
    {
        "key": "assoc_awards_annual",
        "section": "Awards",
        "name": "Annual Awards",
        "slug": "annual-awards",
        "business_type_ids": [BT_ASSOCIATION],
        "default_blocks": [
            {"block_type": "content", "block_data": {
                "heading": "Annual Awards",
                "body": "Categories, nomination criteria, and how winners are selected each year.",
            }},
            {"block_type": "content_3col", "block_data": {"columns": [
                {"heading": "Breeder of the Year",  "body": "Criteria and past winners."},
                {"heading": "Junior of the Year",   "body": "For exceptional junior members."},
                {"heading": "Service award",        "body": "For significant volunteer contributions."},
            ]}},
        ],
    },
]


def list_templates(business_type_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """Return templates applicable to the given BusinessTypeID.
    Templates with business_type_ids=None are universal and always included."""
    out = []
    for tpl in PAGE_TEMPLATES:
        gate = tpl.get("business_type_ids")
        if gate is None or (business_type_id is not None and business_type_id in gate):
            # Strip the default_blocks from the list view — callers fetch them on apply
            out.append({k: v for k, v in tpl.items() if k != "default_blocks"})
    # Stable ordering: section then name
    out.sort(key=lambda t: (t.get("section", ""), t.get("name", "")))
    return out


def get_template(key: str) -> Optional[Dict[str, Any]]:
    for tpl in PAGE_TEMPLATES:
        if tpl["key"] == key:
            return tpl
    return None
