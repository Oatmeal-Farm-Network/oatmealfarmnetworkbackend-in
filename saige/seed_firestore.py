# --- seed_firestore.py --- (Populate Firestore livestock_knowledge collection)
"""
Seeds the Firestore RAG collection with:
  1. Breed documents from SQL Server (~2000)
  2. Species documents from SQL Server (~20-30)
  3. Curated livestock knowledge articles (~60)

Usage:
  python seed_firestore.py                     # Seed if collection is empty
  python seed_firestore.py --force-rebuild     # Clear and rebuild
  python seed_firestore.py --dry-run           # Preview without writing
  python seed_firestore.py --skip-sql          # Only curated articles
  python seed_firestore.py --skip-curated      # Only SQL data
"""

import time
import argparse
from config import (
    DB_CONFIG, GCP_PROJECT, GCP_LOCATION, GCP_CREDENTIALS,
    EMBEDDING_MODEL, FIRESTORE_DATABASE, FIRESTORE_COLLECTION,
)

from google.cloud import firestore
from google.cloud.firestore_v1.vector import Vector
from google.cloud.firestore_v1.base_vector_query import DistanceMeasure
from langchain_google_genai import GoogleGenerativeAIEmbeddings


# ============================================================================
# CLIENT INITIALIZATION
# ============================================================================

def get_firestore_client():
    """Initialize Firestore client (matches rag.py pattern)."""
    credentials = None
    if GCP_CREDENTIALS:
        from google.oauth2 import service_account
        credentials = service_account.Credentials.from_service_account_file(
            GCP_CREDENTIALS,
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
    if credentials:
        return firestore.Client(
            project=GCP_PROJECT, database=FIRESTORE_DATABASE, credentials=credentials
        )
    return firestore.Client(project=GCP_PROJECT, database=FIRESTORE_DATABASE)


def get_embeddings_client():
    """Initialize VertexAI embeddings client."""
    return GoogleGenerativeAIEmbeddings(
        model=EMBEDDING_MODEL,
        project=GCP_PROJECT,
        location=GCP_LOCATION,
    )


# ============================================================================
# SQL DATA EXTRACTION
# ============================================================================

def extract_sql_data():
    """Pull all livestock data from SQL Server."""
    import pymssql

    print("[SQL] Connecting to SQL Server...")
    try:
        conn = pymssql.connect(
            server=DB_CONFIG["host"],
            port=DB_CONFIG["port"],
            user=DB_CONFIG["user"],
            password=DB_CONFIG["password"],
            database=DB_CONFIG["database"],
            as_dict=True,
        )
    except Exception as e:
        print(f"[SQL] Connection failed: {e}")
        print("[SQL] Skipping SQL data extraction. Use --skip-sql to suppress this.")
        return [], []

    cursor = conn.cursor()

    # --- Species ---
    cursor.execute("""
        SELECT SpeciesID, Species, MaleTerm, FemaleTerm, BabyTerm,
               SingularTerm, PluralTerm, GestationPeriod
        FROM Speciesavailable WHERE SpeciesAvailable = 1
    """)
    species_rows = cursor.fetchall()
    print(f"[SQL] Species: {len(species_rows)}")

    # --- Breeds ---
    cursor.execute("""
        SELECT b.BreedLookupID, b.Breed, b.Breeddescription,
               b.MeatBreed, b.MilkBreed, b.WoolBreed, b.EggBreed, b.Working,
               s.Species, s.SpeciesID
        FROM Speciesbreedlookuptable b
        JOIN Speciesavailable s ON b.SpeciesID = s.SpeciesID
        WHERE b.breedavailable = 1
    """)
    breed_rows = cursor.fetchall()
    print(f"[SQL] Breeds: {len(breed_rows)}")

    # --- Colors per species ---
    cursor.execute("SELECT DISTINCT SpeciesID, SpeciesColor FROM Speciescolorlookuptable")
    color_rows = cursor.fetchall()
    colors_by_species = {}
    for row in color_rows:
        sid = row["SpeciesID"]
        colors_by_species.setdefault(sid, []).append(row["SpeciesColor"])

    # --- Patterns per species ---
    cursor.execute("SELECT DISTINCT SpeciesID, SpeciesColor AS Pattern FROM Speciespatternlookuptable")
    pattern_rows = cursor.fetchall()
    patterns_by_species = {}
    for row in pattern_rows:
        sid = row["SpeciesID"]
        patterns_by_species.setdefault(sid, []).append(row["Pattern"])

    # --- Categories per species ---
    cursor.execute("SELECT SpeciesID, SpeciesCategory FROM Speciescategory ORDER BY SpeciesID, SpeciesCategoryOrder")
    category_rows = cursor.fetchall()
    categories_by_species = {}
    for row in category_rows:
        sid = row["SpeciesID"]
        categories_by_species.setdefault(sid, []).append(row["SpeciesCategory"])

    conn.close()

    # --- Format species documents ---
    species_docs = []
    for sp in species_rows:
        sid = sp["SpeciesID"]
        name = sp["Species"] or "Unknown"
        parts = [f"{name} is a livestock species."]

        if sp.get("GestationPeriod"):
            parts.append(f"The gestation period is approximately {sp['GestationPeriod']} days.")

        terms = []
        if sp.get("MaleTerm"): terms.append(f"male: {sp['MaleTerm']}")
        if sp.get("FemaleTerm"): terms.append(f"female: {sp['FemaleTerm']}")
        if sp.get("BabyTerm"): terms.append(f"young: {sp['BabyTerm']}")
        if terms:
            parts.append(f"Terminology: {', '.join(terms)}.")

        cats = categories_by_species.get(sid, [])
        if cats:
            parts.append(f"Categories: {', '.join(cats[:15])}.")

        colors = colors_by_species.get(sid, [])
        if colors:
            parts.append(f"Common colors: {', '.join(colors[:20])}.")

        patterns = patterns_by_species.get(sid, [])
        if patterns:
            parts.append(f"Coat patterns: {', '.join(patterns[:20])}.")

        species_docs.append({
            "id": f"species_{sid}",
            "content": " ".join(parts),
            "metadata": {
                "doc_type": "species",
                "animal_type": name,
                "species_id": str(sid),
            }
        })

    # --- Format breed documents ---
    breed_docs = []
    for br in breed_rows:
        name = br.get("Breed", "Unknown")
        species = br.get("Species", "Unknown")
        desc = br.get("Breeddescription", "") or ""

        purposes = []
        if br.get("MeatBreed"): purposes.append("meat production")
        if br.get("MilkBreed"): purposes.append("dairy/milk production")
        if br.get("WoolBreed"): purposes.append("wool/fiber production")
        if br.get("EggBreed"): purposes.append("egg production")
        if br.get("Working"): purposes.append("working/draft")

        content = f"{name} is a breed of {species}"
        if purposes:
            content += f" primarily used for {', '.join(purposes)}"
        content += "."
        if desc:
            content += f" {desc}"

        breed_docs.append({
            "id": f"breed_{br.get('BreedLookupID', name.replace(' ', '_'))}",
            "content": content,
            "metadata": {
                "doc_type": "breed",
                "animal_type": species,
                "breed_name": name,
                "purposes": purposes,
                "breed_id": str(br.get("BreedLookupID", "")),
                "species_id": str(br.get("SpeciesID", "")),
            }
        })

    print(f"[SQL] Formatted {len(species_docs)} species + {len(breed_docs)} breed documents")
    return species_docs, breed_docs


# ============================================================================
# CURATED KNOWLEDGE ARTICLES
# ============================================================================

CURATED_ARTICLES = [
    # --- BREED SELECTION GUIDES ---
    {
        "id": "guide_dairy_cattle",
        "content": (
            "Best Dairy Cattle Breeds for Small Farms. "
            "Holstein Friesian cattle are the world's highest-producing dairy breed, averaging 22,000-25,000 pounds of milk per year, "
            "but they require excellent nutrition and management. Jersey cattle are ideal for small farms due to their smaller size, "
            "docile temperament, and high butterfat milk (4.9%), making them perfect for cheese and butter production. "
            "Guernsey cattle produce golden-colored milk rich in beta-carotene and protein, with moderate production of 14,000-16,000 pounds yearly. "
            "Brown Swiss are known for longevity and strong feet, producing milk with an ideal protein-to-fat ratio for cheese making. "
            "For very small operations, Dexter cattle are a miniature dual-purpose breed producing 2-3 gallons of milk daily while requiring "
            "only half the feed of standard breeds. When choosing a dairy breed, consider your climate, available pasture, market for milk products, "
            "and whether you need A2 milk (Guernsey and Jersey naturally produce mostly A2 beta-casein protein)."
        ),
        "metadata": {"doc_type": "guide", "animal_type": "Cattle", "category": "breed_selection", "use_case": "dairy"}
    },
    {
        "id": "guide_meat_cattle",
        "content": (
            "Top Meat Cattle Breeds for Beginners. "
            "Angus cattle are the most popular beef breed in North America due to their marbling quality, calving ease, and foraging ability. "
            "Black Angus are particularly valued for their polled (hornless) genetics and docile temperament. "
            "Hereford cattle are known for their hardiness, efficiency on grass, and gentle disposition, making them excellent for first-time cattle owners. "
            "Charolais are large-framed cattle from France that grow rapidly and produce lean, heavy carcasses. "
            "Simmental cattle are versatile, offering both growth rate and milk production for calf rearing. "
            "For small acreage, consider Lowline Angus (miniature Angus) or Dexter cattle which produce quality beef on less pasture. "
            "Red Poll cattle are a gentle, dual-purpose heritage breed well suited to grass-finishing. "
            "When selecting beef cattle, evaluate mature weight (affects fencing and handling), calving ease (especially for heifers), "
            "feed efficiency, and your finishing method (grain-fed vs grass-fed)."
        ),
        "metadata": {"doc_type": "guide", "animal_type": "Cattle", "category": "breed_selection", "use_case": "meat"}
    },
    {
        "id": "guide_dual_purpose_cattle",
        "content": (
            "Dual-Purpose Cattle Breeds for Mixed Farms. "
            "Dual-purpose cattle provide both milk and meat, making them economical for diversified farms. "
            "Shorthorn cattle come in milking and beef strains; the Milking Shorthorn produces 12,000-15,000 pounds of milk per year "
            "while steers finish well for beef. Dexter cattle are a small Irish breed (700-900 lbs) producing 2-3 gallons of milk daily "
            "with calves that finish at 450-500 lbs, perfect for homesteads with limited acreage. "
            "Red Poll cattle are polled, docile, and thrive on grass alone, producing moderate milk while building good beef conformation. "
            "Normande cattle from France are gaining popularity for their high-protein milk (excellent for cheese) and muscular build. "
            "Devon cattle are an ancient British breed known for exceptional grass conversion and rich-flavored beef and milk. "
            "When managing dual-purpose cattle, you typically milk one or two cows for household use while raising surplus calves for beef. "
            "This system requires less specialized equipment than a dedicated dairy but still provides a regular milk supply."
        ),
        "metadata": {"doc_type": "guide", "animal_type": "Cattle", "category": "breed_selection", "use_case": "dual_purpose"}
    },
    {
        "id": "guide_egg_chickens",
        "content": (
            "Best Egg-Laying Chicken Breeds. "
            "White Leghorn chickens are the industry standard for egg production, laying 280-320 large white eggs per year. "
            "They are efficient feed converters but can be flighty. Rhode Island Red chickens are hardy dual-purpose birds laying "
            "250-300 brown eggs yearly, tolerant of cold weather and disease resistant. "
            "Plymouth Rock (Barred Rock) chickens are docile, cold-hardy, and lay 200-280 brown eggs per year, making them ideal for families. "
            "Australorp chickens hold the world record of 364 eggs in 365 days and are calm, friendly birds laying 250-300 light brown eggs. "
            "ISA Brown and Golden Comet are hybrid layers producing 300+ eggs in their first year but decline faster than heritage breeds. "
            "For blue-green eggs, Ameraucana and Easter Egger chickens lay 200-250 colorful eggs yearly. "
            "Marans chickens produce distinctive dark chocolate-brown eggs with 150-200 per year. "
            "Key factors: heritage breeds lay longer (4-5 years) while hybrids peak in year one; "
            "free-range birds need 4 sq ft coop space and 10 sq ft run per bird."
        ),
        "metadata": {"doc_type": "guide", "animal_type": "Chicken", "category": "breed_selection", "use_case": "eggs"}
    },
    {
        "id": "guide_meat_chickens",
        "content": (
            "Meat Chicken Breeds (Broilers) for Small Farms. "
            "Cornish Cross is the standard commercial broiler, reaching 5-6 lbs in just 6-8 weeks with excellent feed conversion. "
            "However, they require careful management to avoid leg problems and heart failure from rapid growth. "
            "Freedom Ranger (Red Ranger) chickens are a slower-growing alternative reaching market weight in 9-11 weeks, "
            "better suited to free-range and pasture systems. They are active foragers with better flavor according to many farmers. "
            "Jersey Giant is the largest purebred chicken, taking 6-9 months to reach 11-13 lbs, best for those who want dual-purpose heritage birds. "
            "Kosher King chickens grow at a moderate pace (12 weeks) and do well on pasture. "
            "For pastured poultry operations, process at 8-12 weeks depending on breed. Cornish Cross need 2 sq ft space "
            "and should have feed restricted after 2 weeks to 12 hours on/12 hours off to prevent growth-related health issues. "
            "Heritage breeds take longer but are more self-sufficient and can reproduce naturally, unlike Cornish Cross."
        ),
        "metadata": {"doc_type": "guide", "animal_type": "Chicken", "category": "breed_selection", "use_case": "meat"}
    },
    {
        "id": "guide_wool_sheep",
        "content": (
            "Wool Sheep Breeds Comparison. "
            "Merino sheep produce the finest wool in the world (11-24 microns) and are the foundation of the wool industry. "
            "They thrive in hot, dry climates and produce 10-20 lbs of greasy wool per shearing. "
            "Rambouillet sheep are the American version of Merino with excellent fine wool and better meat conformation. "
            "Corriedale sheep produce medium-grade wool (25-31 microns) and are a true dual-purpose breed with good meat qualities. "
            "Romney sheep are suited to wet climates with their long, lustrous wool that resists rot; ideal for hand spinners. "
            "Bluefaced Leicester sheep produce fine, lustrous longwool prized by hand spinners and weavers. "
            "For fiber arts, Shetland sheep produce a wide range of natural colors with soft, fine wool. "
            "Jacob sheep are a striking four-horned breed with naturally spotted fleece popular with hand spinners. "
            "Shearing should occur once annually in spring. Wool value ranges from $2 to $20+ per pound depending on breed, "
            "fineness, and preparation. Direct sales to hand spinners often bring the best return for small flocks."
        ),
        "metadata": {"doc_type": "guide", "animal_type": "Sheep", "category": "breed_selection", "use_case": "wool"}
    },
    {
        "id": "guide_meat_sheep",
        "content": (
            "Meat Sheep Breeds for Profitable Lamb Production. "
            "Suffolk sheep are the most popular terminal sire breed producing fast-growing lambs with lean, muscular carcasses. "
            "Hampshire sheep are similar to Suffolk with rapid growth and good meat conformation. "
            "Dorper sheep are a South African hair sheep breed ideal for warm climates, requiring no shearing and producing meaty lambs. "
            "Katahdin sheep are a hardy American hair sheep breed that sheds its coat, resists parasites, and thrives on minimal inputs. "
            "Texel sheep produce extremely muscular, lean carcasses and are popular as terminal sires in crossbreeding programs. "
            "St. Croix sheep are a heat-tolerant hair sheep with excellent parasite resistance, ideal for Southern climates. "
            "For grass-fed lamb, consider Katahdin or Dorper crosses which finish well on pasture alone. "
            "Stocking rate for meat sheep is 5-6 ewes per acre on good pasture. Lambing percentage of 150-200% (1.5-2 lambs per ewe) "
            "is typical for productive flocks. Market lambs are usually sold at 90-140 lbs live weight at 5-8 months of age."
        ),
        "metadata": {"doc_type": "guide", "animal_type": "Sheep", "category": "breed_selection", "use_case": "meat"}
    },
    {
        "id": "guide_dairy_goats",
        "content": (
            "Dairy Goat Breeds for Milk Production. "
            "Saanen goats are the Holstein of the goat world, producing 1-3 gallons per day of lower-fat milk (3-4%). "
            "They are large, white, and calm but sensitive to sun and heat. "
            "Nubian goats produce less volume but the highest butterfat (4-5%), making them ideal for cheese and soap production. "
            "They are recognizable by their long, floppy ears and Roman nose. "
            "Alpine goats are hardy, adaptable, and produce 1-2 gallons daily. They come in many color patterns and are strong foragers. "
            "LaMancha goats are known for their tiny ears and gentle temperament, producing rich milk averaging 4% butterfat. "
            "Toggenburg goats are a Swiss breed producing consistent, lower-fat milk with a distinctive flavor some prefer for drinking. "
            "Nigerian Dwarf goats produce 1-2 quarts daily of high-butterfat milk (6-10%) and are perfect for small properties. "
            "Dairy goats need quality hay, grain on the milk stand (1 lb per 3 lbs milk), fresh water, and loose minerals. "
            "They must be milked twice daily on a consistent schedule. A small dairy goat operation needs at least 2 goats for companionship."
        ),
        "metadata": {"doc_type": "guide", "animal_type": "Goat", "category": "breed_selection", "use_case": "dairy"}
    },
    {
        "id": "guide_meat_goats",
        "content": (
            "Meat Goat Breeds for Profitable Production. "
            "Boer goats are the premier meat breed, originally from South Africa, with rapid growth rates reaching 200-300 lbs. "
            "They have a distinctive white body with a red-brown head and are docile and hardy. "
            "Kiko goats were developed in New Zealand for hardiness and parasite resistance, requiring minimal intervention. "
            "They are excellent mothers and thrive in challenging environments. "
            "Spanish goats are a landrace breed in the American South, extremely hardy and parasite resistant but smaller framed. "
            "Savanna goats are a white South African breed similar to Boer but with better heat tolerance and disease resistance. "
            "Boer-Kiko crosses combine Boer growth rates with Kiko hardiness, a popular commercial cross. "
            "Meat goats need less intensive management than dairy goats. Stocking rate is 6-8 goats per acre on good browse/pasture. "
            "Kids reach market weight (60-80 lbs) at 3-6 months. The ethnic meat market drives most demand, with peak prices "
            "around Easter, Eid, and Christmas. Goats require excellent fencing (4+ feet, no-climb wire) as they are expert escape artists."
        ),
        "metadata": {"doc_type": "guide", "animal_type": "Goat", "category": "breed_selection", "use_case": "meat"}
    },
    {
        "id": "guide_pig_breeds",
        "content": (
            "Pig Breeds for Small and Pasture-Based Farms. "
            "Berkshire pigs are a heritage breed known for exceptional pork quality with marbling, dark color, and rich flavor. "
            "They are docile, good foragers, and adapt well to outdoor systems. "
            "Duroc pigs are fast-growing with excellent meat quality and intramuscular fat, popular in both commercial and small operations. "
            "Tamworth pigs are the best bacon breed with long bodies producing lean, flavorful bacon. They are active foragers and cold-hardy. "
            "Large Black pigs are a docile heritage breed with excellent mothering ability and lard-type pork perfect for charcuterie. "
            "Yorkshire (Large White) pigs are the commercial standard with large litters and rapid growth. "
            "Hampshire pigs produce lean, muscular carcasses and are common in crossbreeding programs. "
            "Kunekune pigs are small, friendly grazers from New Zealand that thrive on grass with minimal supplementation, "
            "ideal for small acreage. For pasture systems, heritage breeds outperform commercial breeds. "
            "Pigs need shade, mud/water for cooling, strong fencing (electric works well), and 20-30 sq ft of shelter per pig."
        ),
        "metadata": {"doc_type": "guide", "animal_type": "Pig", "category": "breed_selection", "use_case": "general"}
    },
    {
        "id": "guide_duck_breeds",
        "content": (
            "Duck Breeds for Eggs and Meat on Small Farms. "
            "Khaki Campbell ducks are the top egg-laying breed, producing 250-340 eggs per year, often outperforming chickens. "
            "Their eggs are larger with richer yolks, excellent for baking. "
            "Pekin ducks are the standard meat breed, reaching 8-9 lbs in 7-8 weeks with white feathers that process cleanly. "
            "They are calm, friendly, and also lay 150-200 eggs per year. "
            "Muscovy ducks are unique (technically not a true duck), producing lean, red meat resembling veal. "
            "They are quiet, excellent foragers, and outstanding for pest control. "
            "Indian Runner ducks are upright, comical birds that lay 200-300 eggs per year and are exceptional slug and insect hunters. "
            "Welsh Harlequin ducks are beautiful, calm birds laying 250-300 eggs per year with good meat conformation. "
            "Ducks are hardier than chickens, more disease resistant, and tolerate cold well. They need access to water for mating "
            "and cleaning but don't require a pond. A kiddie pool or deep trough works. "
            "Ducks need a secure shelter at night but are less vulnerable to predators than chickens."
        ),
        "metadata": {"doc_type": "guide", "animal_type": "Duck", "category": "breed_selection", "use_case": "general"}
    },
    {
        "id": "guide_turkey_breeds",
        "content": (
            "Turkey Breeds for Small Farm Production. "
            "Broad Breasted White turkeys are the commercial standard, reaching 30-40 lbs (toms) in 16-20 weeks. "
            "They cannot reproduce naturally and must be artificially inseminated. "
            "Broad Breasted Bronze are similar in size with beautiful feathering but dark pin feathers affect carcass appearance. "
            "Bourbon Red turkeys are a heritage breed reaching 20-25 lbs with rich, flavorful meat and attractive mahogany plumage. "
            "They can reproduce naturally and are good foragers. "
            "Narragansett turkeys are a calm, hardy heritage breed reaching 18-25 lbs with beautiful steel-gray and white plumage. "
            "Royal Palm turkeys are smaller (12-16 lbs) and primarily ornamental but produce excellent-tasting meat. "
            "Heritage turkeys take 26-30 weeks to reach market weight but command premium prices ($6-10/lb vs $2-3 for commercial). "
            "Turkeys need more space than chickens: 10 sq ft per bird in shelter, 100+ sq ft in range. "
            "Poults (baby turkeys) are fragile for the first 8 weeks and need careful brooding at 95-100F initially."
        ),
        "metadata": {"doc_type": "guide", "animal_type": "Turkey", "category": "breed_selection", "use_case": "general"}
    },
    {
        "id": "guide_horse_breeds",
        "content": (
            "Horse and Draft Breeds for Farms. "
            "Quarter Horses are the most versatile farm breed, excellent for cattle work, trail riding, and general farm use. "
            "They are calm, strong, and easy to train. "
            "Clydesdale horses are a heavy draft breed (1,800-2,200 lbs) used for plowing, logging, and heavy pulling. "
            "They have distinctive feathered legs and are gentle giants. "
            "Percheron horses are another popular draft breed, slightly more versatile than Clydesdales and often used as riding horses too. "
            "Belgian Draft horses are the strongest draft breed, commonly used in farming operations and competitive pulling. "
            "Haflinger horses are a compact, strong breed ideal for small farms, capable of both riding and light draft work. "
            "Mules (horse-donkey cross) are often preferred to horses for farm work due to their sure-footedness, "
            "endurance, lower feed requirements, and resistance to common horse ailments. "
            "A working farm horse needs 1.5-2% of body weight in forage daily, plus grain when working. "
            "Horses require regular farrier work (every 6-8 weeks), dental care (annually), and deworming."
        ),
        "metadata": {"doc_type": "guide", "animal_type": "Horse", "category": "breed_selection", "use_case": "general"}
    },

    # --- LIVESTOCK HEALTH ---
    {
        "id": "guide_cattle_health",
        "content": (
            "Common Cattle Diseases and Prevention. "
            "Bovine Respiratory Disease (BRD) is the leading cause of cattle death, caused by stress combined with viral and bacterial infection. "
            "Prevent with proper vaccination (IBR, BVD, PI3, BRSV), minimize stress during weaning and transport, and ensure good ventilation. "
            "Bovine Viral Diarrhea (BVD) causes reproductive loss, immune suppression, and persistent infection. "
            "Test and remove persistently infected (PI) animals; vaccinate breeding stock. "
            "Bloat occurs when gas builds up in the rumen, can be fatal within hours. "
            "Prevent by introducing legume pastures gradually, providing bloat blocks, and avoiding grazing wet legumes. "
            "Mastitis (udder infection) reduces milk production and quality. Maintain clean bedding, proper milking hygiene, and teat dipping. "
            "Pinkeye (infectious bovine keratoconjunctivitis) spreads rapidly in summer via face flies. "
            "Control flies, provide shade, and treat early with antibiotics. "
            "Clostridial diseases (blackleg, tetanus, enterotoxemia) are prevented by the 7-way or 8-way clostridial vaccine, "
            "typically given at branding/weaning and boosted annually."
        ),
        "metadata": {"doc_type": "guide", "animal_type": "Cattle", "category": "health", "use_case": "disease_prevention"}
    },
    {
        "id": "guide_sheep_health",
        "content": (
            "Sheep Health Management Calendar. "
            "Pre-lambing (6-8 weeks before): Vaccinate ewes with CD/T (Clostridium perfringens C&D and tetanus), "
            "increase nutrition (flushing), trim hooves, and deworm if needed based on fecal egg count. "
            "Lambing: Ensure clean lambing area, dip navels in iodine, ensure colostrum intake within 2 hours, "
            "and band tails within first week if docking. "
            "Spring: Shear before lambing or in early spring, vaccinate lambs with CD/T at 6-8 weeks and booster at 12 weeks. "
            "Summer: Monitor for internal parasites using FAMACHA scoring every 2-3 weeks, rotate pastures, "
            "provide shade and fresh water, watch for fly strike especially in wet conditions. "
            "Fall: Flush ewes (increase nutrition) 2 weeks before breeding, introduce rams, deworm based on fecal egg count. "
            "Winter: Increase hay quality and quantity for pregnant ewes, ensure unfrozen water, "
            "provide windbreaks, selenium/vitamin E supplementation in deficient areas. "
            "Internal parasites (Haemonchus, Teladorsagia) are the number one health threat to sheep. "
            "Use targeted selective treatment based on FAMACHA scoring rather than blanket deworming to slow resistance."
        ),
        "metadata": {"doc_type": "guide", "animal_type": "Sheep", "category": "health", "use_case": "management_calendar"}
    },
    {
        "id": "guide_poultry_health",
        "content": (
            "Poultry Disease Prevention and Biosecurity. "
            "Marek's Disease is a viral disease causing paralysis and tumors in chickens. Vaccinate day-old chicks; "
            "there is no treatment. Newcastle Disease causes respiratory distress and neurological signs; vaccinate in endemic areas. "
            "Coccidiosis is the most common poultry disease, caused by Eimeria protozoa in wet litter. "
            "Prevent with medicated starter feed (Amprolium) or vaccine. Keep litter dry. "
            "Avian Influenza (bird flu) requires strict biosecurity: limit visitor access, quarantine new birds 30 days, "
            "keep wild birds away from feed and water, and report any sudden flock die-offs to authorities. "
            "Mycoplasma Gallisepticum (MG) causes chronic respiratory disease. Buy from NPIP-certified sources. "
            "Bumblefoot is a staph infection from foot injuries on rough roosts or wet ground. Use smooth, rounded roosts. "
            "Biosecurity basics: wear dedicated farm boots, quarantine new birds, clean and disinfect equipment, "
            "control rodents, provide clean water, and maintain proper ventilation (ammonia below 25 ppm). "
            "Have a poultry first aid kit: electrolytes, Vetericyn wound spray, Corid for coccidiosis, and a brooder for isolation."
        ),
        "metadata": {"doc_type": "guide", "animal_type": "Poultry", "category": "health", "use_case": "biosecurity"}
    },
    {
        "id": "guide_goat_health",
        "content": (
            "Goat Health Essentials. "
            "Caprine Arthritis Encephalitis (CAE) is a viral disease causing arthritis and wasting with no cure. "
            "Test annually and cull positive animals; prevent by bottle-feeding kids with heat-treated colostrum. "
            "Caseous Lymphadenitis (CL) causes abscesses in lymph nodes and is highly contagious. "
            "Isolate and carefully drain or cull affected goats; vaccinate with Case-Bac if prevalent in your area. "
            "Internal parasites are the leading cause of goat death. Use FAMACHA scoring every 2 weeks in grazing season. "
            "The barber pole worm (Haemonchus contortus) causes anemia and bottle jaw. "
            "Rotate pastures every 3-4 weeks, don't graze below 4 inches, and use targeted deworming. "
            "Copper deficiency is common in goats causing rough coat, poor growth, and parasite susceptibility. "
            "Supplement with copper oxide wire particles (COWP) boluses. "
            "Enterotoxemia (overeating disease) kills fast-growing kids suddenly. Prevent with CD/T vaccination at 4 weeks, "
            "8 weeks, and annually. Urinary calculi in bucks/wethers is prevented by maintaining a 2:1 calcium-to-phosphorus ratio "
            "and adding ammonium chloride to feed. Hoof rot is prevented by regular trimming every 6-8 weeks and keeping areas dry."
        ),
        "metadata": {"doc_type": "guide", "animal_type": "Goat", "category": "health", "use_case": "disease_prevention"}
    },
    {
        "id": "guide_pig_health",
        "content": (
            "Pig Health Management. "
            "Porcine Reproductive and Respiratory Syndrome (PRRS) is the most economically devastating pig disease worldwide. "
            "It causes reproductive failure in sows and respiratory disease in piglets. Vaccinate breeding stock and maintain closed herd. "
            "Swine influenza causes coughing, fever, and reduced growth. It spreads rapidly; provide good ventilation and vaccinate. "
            "Erysipelas causes diamond-shaped skin lesions, arthritis, and sudden death. Vaccinate sows before farrowing. "
            "Mange (Sarcoptes scabiei) causes intense itching and skin crusting. Treat with ivermectin and clean housing thoroughly. "
            "Mycoplasma pneumonia causes chronic cough in growing pigs. Improve ventilation, reduce stocking density, "
            "and vaccinate at weaning. Diarrhea in piglets (scours) is prevented by ensuring colostrum intake, "
            "clean farrowing pens, and iron injections at 2-3 days old. "
            "Internal parasites are managed with rotational deworming (ivermectin or fenbendazole) every 3-4 months. "
            "Heat stress is a major concern for pigs since they cannot sweat. Provide shade, wallows or misters, "
            "and increase water access when temperatures exceed 80F. Mortality increases sharply above 90F."
        ),
        "metadata": {"doc_type": "guide", "animal_type": "Pig", "category": "health", "use_case": "disease_prevention"}
    },
    {
        "id": "guide_vaccination_schedules",
        "content": (
            "Livestock Vaccination Schedules by Species. "
            "CATTLE: Core vaccines include 7-way Clostridial (blackleg, tetanus, enterotoxemia) at branding, "
            "weaning booster, then annual. Modified-live 5-way viral (IBR, BVD, PI3, BRSV, Lepto) for breeding animals. "
            "Calves: first round at 2-4 months, booster at weaning. "
            "SHEEP/GOATS: CD/T vaccine is essential. Lambs/kids at 6-8 weeks with 12-week booster. "
            "Ewes/does 4-6 weeks pre-lambing/kidding. Annual booster. Rabies where required by law. "
            "Soremouth vaccine only if disease is present on farm (live vaccine). "
            "PIGS: Erysipelas at 8 weeks, booster at 12 weeks. Sows: Erysipelas, Lepto, Parvo before breeding. "
            "E. coli scours vaccine for sows 5 and 2 weeks before farrowing. Mycoplasma at weaning if endemic. "
            "POULTRY: Marek's at hatchery (day-old). Newcastle-Bronchitis at 14-18 days via water. "
            "Fowl pox at 8-12 weeks via wing web. Booster Newcastle at point of lay. "
            "HORSES: Core vaccines (EEE/WEE, West Nile, Tetanus, Rabies) annually in spring. "
            "Risk-based: influenza, rhinopneumonitis, strangles. Always consult your local veterinarian for area-specific recommendations."
        ),
        "metadata": {"doc_type": "guide", "animal_type": "All", "category": "health", "use_case": "vaccination"}
    },
    {
        "id": "guide_parasite_management",
        "content": (
            "Internal Parasite Management in Ruminants. "
            "The barber pole worm (Haemonchus contortus) is the most dangerous internal parasite of sheep, goats, and cattle, "
            "causing severe anemia and death. "
            "FAMACHA scoring examines the inner eyelid color to estimate anemia level and identify animals needing treatment. "
            "Score 1-2 (red/dark pink) is healthy; score 4-5 (white/pale) needs immediate treatment. "
            "Rotational grazing is the best parasite control tool. Move animals to fresh pasture every 3-4 weeks. "
            "Parasites concentrate in the bottom 2 inches of grass, so never graze below 4 inches. "
            "Rest pastures for 60-90 days to break parasite life cycles. Multi-species grazing (cattle with sheep/goats) "
            "reduces parasite loads since most parasites are host-specific. "
            "Dewormer classes: Benzimidazoles (fenbendazole), Macrocyclic lactones (ivermectin, moxidectin), "
            "and Levamisole. Rotate classes annually, not within a season. "
            "Do fecal egg counts before and 10-14 days after deworming to check effectiveness. "
            "Resistance is widespread; over 90% of farms have some dewormer resistance. "
            "Copper oxide wire particles (COWP) boluses can reduce barber pole worm loads in sheep and goats by 50-90%."
        ),
        "metadata": {"doc_type": "guide", "animal_type": "Ruminants", "category": "health", "use_case": "parasite_control"}
    },
    {
        "id": "guide_heat_stress",
        "content": (
            "Heat Stress Management in Livestock. "
            "Heat stress reduces feed intake, growth, milk production, and reproductive performance. "
            "CATTLE: Dairy cows suffer above 72F with humidity. Provide shade (40-60 sq ft per cow), fans, "
            "and sprinklers that wet the cow then allow evaporation. Ensure 30+ gallons of cool water per cow per day. "
            "Feed early morning and late evening. Consider feeding more digestible rations that generate less metabolic heat. "
            "SHEEP: Shear before hot weather. Provide shade and fresh water. Watch for respiratory rate above 80/min. "
            "PIGS: Most vulnerable since they cannot sweat. Provide wallows, shade, and misters. "
            "Reduce stocking density in summer. Mortality risk increases sharply above 90F. "
            "POULTRY: Chickens pant above 85F. Ensure excellent ventilation, cool water with electrolytes, "
            "frozen treats, shade over runs. Egg production drops significantly above 90F. "
            "Mortality occurs rapidly above 104F. GOATS: More heat-tolerant than sheep but still need shade and water. "
            "Hair breeds tolerate heat better than wooled breeds. "
            "General signs of heat stress: panting, drooling, lethargy, reduced feed intake, standing in water. "
            "Severe cases: staggering, collapse, body temperature above 105F requires immediate cooling."
        ),
        "metadata": {"doc_type": "guide", "animal_type": "All", "category": "health", "use_case": "heat_stress"}
    },
    {
        "id": "guide_cold_weather",
        "content": (
            "Cold Weather Livestock Care. "
            "CATTLE: Beef cattle are cold-hardy to 0F with dry conditions and wind protection. "
            "Increase hay by 1% of body weight for every 10F below the lower critical temperature. "
            "Ensure unfrozen water (heated tanks or frequent breaking). Provide windbreaks (solid walls, tree lines, or 80% wind reduction fencing). "
            "Body condition score should be 5-6 entering winter. Calving in extreme cold requires heated areas or calf jackets. "
            "SHEEP: Most breeds tolerate cold well with full fleece. Shearing should NOT be done in winter. "
            "Newborn lambs are vulnerable; provide heat lamps and jugs (small lambing pens). "
            "Increase grain for late-gestation ewes. Deep bedding (12+ inches of straw) provides insulation. "
            "GOATS: Less cold-tolerant than sheep. Need draft-free shelter with deep bedding. "
            "Angora and fiber goats need protection from rain when shorn. "
            "PIGS: Need insulated shelter below 50F. Deep straw bedding works well. "
            "POULTRY: Insulate coops but maintain ventilation (moisture is worse than cold). "
            "Wide roosts (2-4 inches) let chickens cover their feet. Frostbite affects large combs; "
            "apply petroleum jelly in extreme cold. Do NOT heat coops as fire risk is extreme."
        ),
        "metadata": {"doc_type": "guide", "animal_type": "All", "category": "health", "use_case": "cold_weather"}
    },
    {
        "id": "guide_nutrition_fundamentals",
        "content": (
            "Livestock Nutrition Fundamentals. "
            "All livestock need six nutrient classes: water, energy, protein, minerals, vitamins, and fiber. "
            "WATER is the most critical nutrient. Dairy cows need 30-50 gallons/day, beef cattle 10-20, "
            "sheep/goats 1-4 gallons, pigs 3-5 gallons, chickens 500ml per bird. "
            "ENERGY comes from carbohydrates and fats. Measured as TDN (Total Digestible Nutrients) or ME (Metabolizable Energy). "
            "Grain (corn, barley, oats) provides concentrated energy; hay and pasture provide fiber-based energy. "
            "PROTEIN needs vary: lactating dairy cows need 16-18% CP, growing lambs 14-16%, "
            "laying hens 16-18%, finishing pigs 14-16%. Soybean meal, alfalfa, and canola meal are common protein supplements. "
            "MINERALS: Calcium and phosphorus ratio should be 2:1. Salt should be offered free-choice. "
            "Selenium, copper, and zinc are commonly deficient. Cattle and sheep have opposite copper needs; "
            "sheep are highly susceptible to copper toxicity while goats require copper supplementation. "
            "VITAMINS: Ruminants synthesize B vitamins in the rumen. Vitamins A, D, E may need supplementation, "
            "especially for animals on stored feeds. Newborn ruminants and all monogastrics need dietary B vitamins."
        ),
        "metadata": {"doc_type": "guide", "animal_type": "All", "category": "health", "use_case": "nutrition"}
    },
    {
        "id": "guide_illness_signs",
        "content": (
            "Signs of Illness in Livestock: Early Detection Guide. "
            "Early detection saves lives and money. Check animals daily and know what normal looks like for each species. "
            "GENERAL WARNING SIGNS across all species: reduced feed/water intake, isolation from the group, "
            "lethargy or depression, abnormal posture (hunched, head down), abnormal gait or limping, "
            "diarrhea or constipation, nasal or eye discharge, coughing or labored breathing, "
            "swelling of joints or abdomen, and changes in manure consistency. "
            "CATTLE SPECIFIC: drooping ears, grinding teeth (sign of pain), bloated left side (rumen bloat), "
            "straining to urinate (urinary calculi in steers), milk drop in dairy cows. "
            "SHEEP/GOATS: bottle jaw (swelling under chin indicates anemia from parasites), "
            "pale inner eyelids, rough/dull coat, teeth grinding, going off feed suddenly. "
            "PIGS: blotchy skin, coughing, vomiting, reluctance to stand, tail biting by pen mates. "
            "POULTRY: ruffled feathers, pale comb, drop in egg production, sneezing, watery eyes, "
            "blood in droppings (coccidiosis), sudden deaths. "
            "TAKE TEMPERATURE if you suspect illness. Normal ranges: cattle 101-102.5F, sheep/goats 101.5-103.5F, "
            "pigs 101-103F, chickens 105-107F, horses 99-101.5F."
        ),
        "metadata": {"doc_type": "guide", "animal_type": "All", "category": "health", "use_case": "early_detection"}
    },

    # --- PRACTICAL FARMING ---
    {
        "id": "guide_fencing",
        "content": (
            "Fencing Options for Different Livestock. "
            "CATTLE: Barbed wire (4-5 strands) is traditional and economical at $0.50-1.00/ft. "
            "High-tensile electric (2-3 strands) is most cost-effective for rotational grazing at $0.25-0.50/ft. "
            "Board fencing is attractive but expensive ($3-6/ft) and needs maintenance. "
            "SHEEP: Woven wire (non-climb) with 4x4 inch mesh, 48 inches tall. Sheep test fences by pushing through, "
            "not jumping. Add a hot wire at nose height. $1.50-3.00/ft installed. "
            "GOATS: The most challenging to fence. 4-foot non-climb woven wire with hot wire top and bottom. "
            "Goats will stand on, crawl under, and squeeze through any weakness. Electric net fencing works well "
            "for rotational grazing. Never use barbed wire for goats as they get tangled. "
            "PIGS: Two strands of electric wire at 8 and 16 inches height is sufficient for trained pigs. "
            "Train piglets to electric fence in a small pen first. Hog panels (cattle panels) for permanent areas. "
            "POULTRY: Chicken wire or hardware cloth for predator protection. Electric poultry netting (42-48 inches) "
            "is ideal for rotational free-range systems. Bury wire 12 inches to prevent digging predators. "
            "HORSES: Board, pipe, vinyl, or high-tensile smooth wire. Never use barbed wire for horses."
        ),
        "metadata": {"doc_type": "guide", "animal_type": "All", "category": "farming", "use_case": "fencing"}
    },
    {
        "id": "guide_rotational_grazing",
        "content": (
            "Rotational Grazing Systems Explained. "
            "Rotational grazing divides pasture into paddocks, grazing one while others rest and regrow. "
            "Benefits: 30-70% more forage production, better animal nutrition, parasite control, "
            "improved soil health, and more even manure distribution. "
            "BASIC ROTATION: Divide pasture into 4-8 paddocks. Graze each for 3-7 days, rest 21-45 days. "
            "Move when grass is grazed to 3-4 inches (never below). Rest period varies by season and growth rate. "
            "INTENSIVE (MOB GRAZING): High stock density for 12-24 hours then move. Mimics wild herd behavior. "
            "Excellent for soil building but requires daily management and water access in each cell. "
            "STOCKING RATE: On good improved pasture, expect 1 animal unit (1,000 lb cow) per 2-3 acres. "
            "With good rotational management, this can improve to 1 AU per 1-1.5 acres. "
            "6 sheep or goats equal approximately 1 animal unit. "
            "INFRASTRUCTURE: Water access in each paddock is critical. Use a central water point with lanes, "
            "or portable tanks. Electric fencing makes paddock creation flexible and affordable. "
            "Monitor forage height before and after grazing. Keep records of rest days and forage condition. "
            "Adjust rotation speed based on season: faster in spring flush, slower in summer drought."
        ),
        "metadata": {"doc_type": "guide", "animal_type": "All", "category": "farming", "use_case": "grazing"}
    },
    {
        "id": "guide_livestock_housing",
        "content": (
            "Livestock Housing Requirements by Species. "
            "CATTLE: Beef cattle need minimal shelter; a three-sided loafing shed or windbreak suffices in most climates. "
            "Allow 35-50 sq ft per cow under cover. Dairy cattle need a milking parlor/barn with at least 80-100 sq ft per cow. "
            "Freestall barns with individual stalls (48x96 inches for Holsteins) are standard for dairy. "
            "SHEEP: Need a dry, draft-free barn for lambing. Allow 15-20 sq ft per ewe. Lambing jugs (5x5 ft pens) "
            "for individual ewes. Ventilation is critical; moisture causes pneumonia. Avoid tight, warm barns. "
            "GOATS: Need more shelter than sheep; they hate rain. Allow 15-20 sq ft per goat plus an elevated sleeping platform. "
            "Dairy goats need a milking stand area. Good ventilation but no drafts. "
            "PIGS: Need shade and shelter year-round. Minimum 8 sq ft per finishing pig, 48 sq ft per sow with litter. "
            "Farrowing crates or huts protect piglets from being crushed. Deep straw bedding for outdoor systems. "
            "POULTRY: 4 sq ft per chicken inside coop, 10 sq ft in run. 8-10 inches of roost space per bird. "
            "One nest box per 4-5 hens. Ventilation at the roofline, not at bird level. "
            "HORSES: 12x12 ft stall minimum, 12x14 ft for large breeds. Run-in sheds for pastured horses."
        ),
        "metadata": {"doc_type": "guide", "animal_type": "All", "category": "farming", "use_case": "housing"}
    },
    {
        "id": "guide_feed_storage",
        "content": (
            "Feed Storage and Management for Livestock. "
            "HAY: Store under cover on pallets to prevent ground moisture wicking. A properly stored hay bale lasts 2+ years. "
            "Outdoor storage loses 15-35% of nutritional value. Hay should be 15-18% moisture at baling; above 20% risks mold and fire. "
            "Test hay quality annually: protein, TDN, and mineral content. Alfalfa hay averages 18-20% protein, "
            "grass hay averages 8-12%. "
            "GRAIN: Store in rodent-proof bins (metal or sealed plastic). Keep dry and ventilated. "
            "Whole grain stores longer than ground. Corn, oats, barley should be below 13% moisture. "
            "Check stored grain monthly for heating, which indicates mold. "
            "SILAGE: Must be packed tightly to exclude oxygen. Horizontal bunker silos or wrapped round bales. "
            "Good silage should smell sweet/vinegary, not rancid or tobacco-like. pH should be below 4.5. "
            "SUPPLEMENTS: Store minerals and vitamins in a cool, dry place. Mineral blocks and loose minerals "
            "have 1-2 year shelf life. Liquid supplements need frost protection. "
            "FEED SAFETY: Moldy feed can cause mycotoxin poisoning, abortion, and death. "
            "Never feed cattle feed containing monensin (Rumensin) to horses as it is fatal. "
            "Keep feed rooms locked to prevent livestock gorging which causes bloat or founder."
        ),
        "metadata": {"doc_type": "guide", "animal_type": "All", "category": "farming", "use_case": "feed_management"}
    },
    {
        "id": "guide_breeding_management",
        "content": (
            "Breeding Management Basics for Livestock. "
            "CATTLE: Cows cycle every 21 days with 12-18 hour standing heat. Breed 12 hours after first standing heat. "
            "AI (artificial insemination) costs $15-30/straw plus technician fee but gives access to superior genetics. "
            "Bull-to-cow ratio: 1 mature bull per 25-30 cows. Gestation: 283 days average. "
            "SHEEP: Ewes are seasonal breeders (fall/winter). Rams can be introduced August-November for winter/spring lambs. "
            "Ram-to-ewe ratio: 1 per 30-50 ewes. Use marking harness on ram to track breeding dates. Gestation: 147 days. "
            "GOATS: Does cycle every 21 days, primarily fall breeders but some breed year-round. "
            "Buck-to-doe ratio: 1 per 25-30 does. Gestation: 150 days. "
            "PIGS: Sows cycle every 21 days year-round. Breed on second heat after weaning. "
            "Boar-to-sow ratio: 1 per 15-20 sows. Gestation: 114 days (3 months, 3 weeks, 3 days). "
            "POULTRY: 1 rooster per 8-12 hens for fertile eggs. Collect eggs daily for hatching; "
            "store at 55F, set in incubator within 7 days. Chicken incubation: 21 days, duck: 28 days, turkey: 28 days. "
            "RECORD KEEPING: Track breeding dates, sire/dam, birth weights, number of offspring, "
            "and any complications to improve genetics over time."
        ),
        "metadata": {"doc_type": "guide", "animal_type": "All", "category": "farming", "use_case": "breeding"}
    },
    {
        "id": "guide_predator_protection",
        "content": (
            "Predator Protection for Livestock. "
            "Common predators by region: coyotes (everywhere), wolves (Northern/Western US), mountain lions (Western), "
            "bears (forested areas), eagles (lambs/kids), foxes and raccoons (poultry), and domestic dogs (surprisingly common). "
            "GUARDIAN ANIMALS: Livestock Guardian Dogs (LGDs) are the gold standard. Great Pyrenees, Anatolian Shepherd, "
            "and Akbash are popular breeds. Raise puppy with livestock from 8 weeks. Need 1-2 dogs per 100 acres. "
            "Donkeys are effective against single coyotes and dogs; use jennies or geldings (not jacks). "
            "Llamas work well with small flocks of sheep/goats; use single gelded males. "
            "FENCING: Electric fencing deters most predators. Add a hot wire at 6 inches (coyotes dig) "
            "and at 48 inches (climbers). Night penning in secure areas dramatically reduces losses. "
            "POULTRY SPECIFIC: Secure coop nightly (automatic door closers are worthwhile). "
            "Hardware cloth (not chicken wire which raccoons can tear). Covered runs prevent aerial predators. "
            "MANAGEMENT: Remove dead livestock promptly (attracts predators). Use motion-activated lights and sirens. "
            "Birthing animals are most vulnerable; supervise or confine during lambing/kidding/calving season."
        ),
        "metadata": {"doc_type": "guide", "animal_type": "All", "category": "farming", "use_case": "predator_protection"}
    },
    {
        "id": "guide_pasture_management",
        "content": (
            "Pasture Management and Renovation. "
            "A productive pasture provides the cheapest livestock feed available. "
            "SOIL TESTING: Test every 2-3 years for pH, phosphorus, potassium, and organic matter. "
            "Most grasses thrive at pH 6.0-7.0. Lime if needed (takes 6-12 months to work). "
            "Apply fertilizer based on soil test results, not guesses. "
            "GRASS SPECIES: Cool-season (fescue, orchardgrass, ryegrass, bluegrass) grow spring and fall. "
            "Warm-season (bermudagrass, bahiagrass, big bluestem) grow summer. Mix both for year-round grazing. "
            "LEGUMES: Adding clover or alfalfa to grass pastures fixes nitrogen (50-200 lbs/acre/year), "
            "increases protein content, and extends grazing season. Frost-seed red clover into existing pasture in late winter. "
            "OVERSEEDING: Broadcast seed into existing pasture in early spring or fall after close grazing. "
            "Drill seeding gives better establishment. Do not bury seed more than 0.25-0.5 inches. "
            "WEED CONTROL: Maintain dense stands through good fertility and grazing management. "
            "Mow or clip pastures after grazing to control seed heads. Spot-spray broadleaf weeds if needed. "
            "SACRIFICE AREAS: Designate a small paddock for heavy use during wet weather to protect other pastures from damage."
        ),
        "metadata": {"doc_type": "guide", "animal_type": "All", "category": "farming", "use_case": "pasture"}
    },
    {
        "id": "guide_manure_management",
        "content": (
            "Manure Management and Composting for Livestock Farms. "
            "Livestock manure is a valuable fertilizer containing nitrogen, phosphorus, and potassium. "
            "A 1,000 lb cow produces 80 lbs of manure per day; 100 laying hens produce about 30 lbs daily. "
            "COMPOSTING: Mix manure with carbon-rich material (straw, wood chips, leaves) at a 25-30:1 carbon-to-nitrogen ratio. "
            "Turn pile every 1-2 weeks. Internal temperature should reach 130-150F for 3+ days to kill pathogens and weed seeds. "
            "Finished compost is dark, crumbly, and earthy-smelling, ready in 3-6 months. "
            "DIRECT APPLICATION: Apply raw manure to fields at least 120 days before harvesting crops eaten raw, "
            "90 days for crops not touching soil (USDA organic rules). "
            "APPLICATION RATES: Cattle manure at 10-15 tons/acre on pasture, based on soil test nitrogen needs. "
            "Poultry manure is much more concentrated; apply 2-4 tons/acre. Over-application causes nutrient runoff. "
            "STORAGE: Manure storage should be at least 100 feet from water sources and wells. "
            "Stack on concrete or compacted clay to prevent groundwater contamination. "
            "Cover compost piles to prevent nutrient leaching from rain. "
            "REGULATIONS: Many states require nutrient management plans for operations above certain animal thresholds."
        ),
        "metadata": {"doc_type": "guide", "animal_type": "All", "category": "farming", "use_case": "manure"}
    },
    {
        "id": "guide_integrated_farming",
        "content": (
            "Integrated Crop-Livestock Farming Systems. "
            "Integrating crops and livestock creates synergies that reduce costs and improve sustainability. "
            "MANURE CYCLING: Livestock manure fertilizes cropland, reducing or eliminating commercial fertilizer costs. "
            "A dairy cow produces enough nutrients annually for 2-3 acres of corn. "
            "COVER CROP GRAZING: Plant cover crops (cereal rye, turnips, radishes) after cash crop harvest "
            "and graze them with cattle or sheep in fall/winter. This adds organic matter, reduces erosion, and provides free feed. "
            "CROP RESIDUE GRAZING: Cattle can graze corn stalks after harvest, utilizing 30-40% of residue. "
            "Limit grazing to prevent soil compaction on wet fields. "
            "SILVOPASTURE: Combining trees, forage, and livestock. Trees provide shade for animals and potential timber income. "
            "Nut trees (walnut, chestnut) or fruit trees with grazing underneath maximize land use. "
            "MULTI-SPECIES GRAZING: Running cattle followed by sheep followed by chickens on the same pasture. "
            "Each species eats different plants and parasites are not shared. Joel Salatin's Polyface Farm model. "
            "PEST CONTROL: Chickens and guinea fowl reduce tick and fly populations in pastures. "
            "Ducks control slugs in vegetable gardens. Goats clear brush and invasive species."
        ),
        "metadata": {"doc_type": "guide", "animal_type": "All", "category": "farming", "use_case": "integrated_systems"}
    },
    {
        "id": "guide_starting_livestock_farm",
        "content": (
            "Starting a Small Livestock Farm: Essential Checklist. "
            "STEP 1 - PLANNING: Define your goals (income, self-sufficiency, hobby). Research local markets and regulations. "
            "Write a basic business plan with expected expenses and income. Start small and scale up. "
            "STEP 2 - LAND: Minimum 2-5 acres for a small operation. Assess soil quality, water availability, "
            "fencing condition, and existing structures. Check zoning for livestock allowances. "
            "STEP 3 - INFRASTRUCTURE BEFORE ANIMALS: Fencing, water system, basic shelter, and feed storage must be ready "
            "before bringing animals home. Budget 40-60% of startup costs for infrastructure. "
            "STEP 4 - CHOOSE YOUR SPECIES: Match to your climate, land, market, and experience level. "
            "Easiest for beginners: chickens, then goats or sheep, then cattle, then pigs. "
            "STEP 5 - SOURCE QUALITY ANIMALS: Buy from reputable breeders. Ask for health records and test results. "
            "Start with young, healthy stock. Quarantine new animals 30 days. "
            "STEP 6 - VETERINARY RELATIONSHIP: Establish a relationship with a large-animal vet before emergencies. "
            "Learn basic health checks yourself. "
            "STEP 7 - MARKETING: Research local demand. Farmers markets, restaurants, and direct sales typically bring "
            "the highest returns. Consider USDA organic or animal welfare certifications for premium markets. "
            "BUDGET: Expect to invest $5,000-15,000 for a small starter operation, with income starting in year 2."
        ),
        "metadata": {"doc_type": "guide", "animal_type": "All", "category": "farming", "use_case": "getting_started"}
    },

    # --- SPECIFIC USE-CASE GUIDES ---
    {
        "id": "guide_small_dairy_operation",
        "content": (
            "Setting Up a Small Dairy Operation. "
            "A small dairy (1-10 cows) can provide milk for your family and additional income from direct sales. "
            "EQUIPMENT: Milking machine or hand milking setup, stainless steel bucket, milk strainer and filters, "
            "bulk tank or glass jars for storage, refrigeration to 38F within 2 hours of milking. "
            "Budget $1,000-5,000 for basic equipment for 1-3 cows, or $10,000+ for a small parlor. "
            "SCHEDULE: Milk twice daily, 12 hours apart, at consistent times. Each cow takes 5-10 minutes to milk. "
            "Total daily commitment: 2-3 hours for milking, cleaning, and feeding. "
            "PRODUCTION: A family cow produces 3-8 gallons per day depending on breed. "
            "Jersey or Guernsey cows are ideal for small dairies due to rich milk and manageable size. "
            "REGULATIONS: Raw milk sale laws vary by state. Some allow on-farm sales, some require retail permits, "
            "some ban raw milk sales entirely. Check your state's dairy regulations before selling. "
            "Many states allow value-added products (cheese, butter, yogurt) with a commercial kitchen. "
            "BREEDING: Breed for fall calving to maximize winter milk production when demand is highest. "
            "Dry off cows 60 days before calving. A cow must have a calf yearly to maintain milk production."
        ),
        "metadata": {"doc_type": "guide", "animal_type": "Cattle", "category": "use_case", "use_case": "small_dairy"}
    },
    {
        "id": "guide_backyard_chickens",
        "content": (
            "Backyard Chicken Keeping Guide. "
            "Chickens are the easiest livestock to start with, providing eggs, pest control, and entertainment. "
            "START WITH: 3-6 hens for a family of four (each hen lays 4-6 eggs per week in peak production). "
            "No rooster needed for eggs, only for fertile eggs. Check local ordinances; many allow hens but not roosters. "
            "COOP: Minimum 4 sq ft per bird inside, 10 sq ft per bird in the run. Include roosts (8-10 inches per bird), "
            "nest boxes (1 per 4 hens), ventilation at roof peak, and predator-proof construction (hardware cloth, not chicken wire). "
            "FEEDING: Layer feed (16% protein) as primary diet. Provide oyster shell free-choice for calcium. "
            "Grit if they don't free-range. Treats (scratch grain, vegetables, mealworms) should be less than 10% of diet. "
            "Fresh water daily with clean waterers. "
            "DAILY CARE: 10-15 minutes morning (let out, check water/feed, collect eggs) and evening (close coop, "
            "check for eggs). Weekly: clean waterers, add bedding. Monthly: deep clean coop. "
            "FIRST EGGS: Pullets start laying at 18-22 weeks. Production peaks at 1-2 years and gradually declines. "
            "Hens molt annually in fall, stopping egg production for 2-3 months while regrowing feathers. "
            "Supplemental light (14 hours total) maintains winter production but may shorten laying life."
        ),
        "metadata": {"doc_type": "guide", "animal_type": "Chicken", "category": "use_case", "use_case": "backyard_chickens"}
    },
    {
        "id": "guide_grass_fed_beef",
        "content": (
            "Raising Grass-Fed Beef Cattle. "
            "Grass-fed beef commands premium prices ($7-12/lb hanging weight vs $3-5 for conventional) "
            "and requires no grain purchases but demands excellent pasture management. "
            "BREED SELECTION: British breeds (Angus, Hereford, Devon, Shorthorn) finish better on grass than Continental breeds. "
            "Smaller-framed cattle reach finish condition faster on grass. "
            "PASTURE: Plan for 2-3 acres per animal with good rotational grazing. "
            "Mixed grass-legume pastures (orchardgrass-clover or fescue-clover) provide the best nutrition. "
            "Stockpile fescue for fall/winter grazing to reduce hay feeding. "
            "TIMELINE: Grass-fed cattle take 24-30 months to finish (vs 14-18 months for grain-fed). "
            "Target finish weight: 1,000-1,200 lbs with 0.3+ inches of backfat. "
            "Use ultrasound to check backfat before scheduling processing. "
            "FINISHING: The last 90 days are critical. Animals need the highest quality forage available. "
            "Lush spring or fall pasture is ideal. Summer slump and winter hay often produce lean, tough meat. "
            "MARKETING: Sell as whole, half, or quarter beef direct to consumers. "
            "A 1,100 lb steer yields approximately 450 lbs of retail cuts. "
            "Develop relationships with local USDA-inspected processors (book 6-12 months ahead). "
            "AGA (American Grassfed Association) certification adds value for marketing."
        ),
        "metadata": {"doc_type": "guide", "animal_type": "Cattle", "category": "use_case", "use_case": "grass_fed_beef"}
    },
    {
        "id": "guide_guardian_animals",
        "content": (
            "Livestock Guardian Animals: Selection and Training. "
            "Guardian animals protect sheep, goats, poultry, and other vulnerable livestock from predators. "
            "LIVESTOCK GUARDIAN DOGS (LGDs): Most effective option. Popular breeds: Great Pyrenees (calm, good with families), "
            "Anatolian Shepherd (independent, good for large acreage), Akbash (athletic, good in hot climates), "
            "Maremma (excellent with poultry and small stock). "
            "Training: Start puppy at 8 weeks old living with the livestock it will protect. "
            "Supervise initially to correct any chasing or playing with stock. Full reliability takes 18-24 months. "
            "Feed separately from livestock. Provide shelter in the pasture. One dog protects 30-100 acres; "
            "use two dogs for larger areas or heavy predator pressure (they work as a team). "
            "GUARDIAN DONKEYS: Use standard or mammoth jennies/geldings (not jacks who may attack livestock). "
            "Effective against single coyotes and dogs. One donkey per 30-50 head of sheep/goats. "
            "Bond by penning with livestock for 4-6 weeks. Don't use with very small lambs/kids as donkeys may injure them. "
            "GUARDIAN LLAMAS: Single gelded male per flock of 100-200 sheep. "
            "Llamas alert with alarm calls and charge predators. Less effective in rough terrain or against wolves. "
            "COSTS: LGD puppy $300-800 + $1,000/year feed/vet. Donkey $500-2,000. Llama $200-1,000."
        ),
        "metadata": {"doc_type": "guide", "animal_type": "All", "category": "use_case", "use_case": "guardian_animals"}
    },
    {
        "id": "guide_livestock_water",
        "content": (
            "Water Requirements and Systems for Livestock. "
            "Water is the most critical nutrient. Livestock with restricted water intake reduce feed intake by 50% within days. "
            "DAILY REQUIREMENTS: Dairy cow (lactating) 30-50 gallons, beef cow 10-20 gallons, "
            "horse 10-15 gallons, sheep/goat 1-4 gallons, pig 3-5 gallons, laying hen 500ml, turkey 800ml. "
            "Requirements double in hot weather and increase 50% for lactating animals. "
            "WATER QUALITY: Test annually for nitrates, bacteria, TDS, and pH. Cattle tolerate 3,000 ppm TDS; "
            "poultry less than 2,000 ppm. Blue-green algae in ponds can be fatal. Nitrates above 100 ppm cause problems. "
            "DELIVERY SYSTEMS: Automatic waterers save labor and ensure fresh supply. "
            "Float valves with stock tanks are simple and reliable. Pasture pipeline systems serve multiple paddocks. "
            "Gravity-fed from a pond or spring is cheapest if elevation allows. Solar-powered pumps for remote pastures. "
            "WINTER: Heated tanks or de-icers prevent freezing ($50-200). Insulated tank covers reduce energy use. "
            "Check daily in winter as heater failures mean no water within hours. "
            "Tank capacity: provide enough for 2 days' supply in case of system failure. "
            "A 300-gallon tank serves 15-20 beef cows for one day. "
            "HYGIENE: Clean tanks weekly in summer (algae growth). Locate away from manure areas. "
            "Concrete aprons around tanks prevent mud and contamination."
        ),
        "metadata": {"doc_type": "guide", "animal_type": "All", "category": "farming", "use_case": "water_systems"}
    },
    {
        "id": "guide_record_keeping",
        "content": (
            "Livestock Record Keeping Essentials. "
            "Good records improve management decisions, track profitability, and are required for many certifications. "
            "INDIVIDUAL ANIMAL RECORDS: ID number/tag, birth date, sire and dam, breed, purchase date and source, "
            "weight at key milestones (birth, weaning, yearling, market), health events (vaccinations, treatments, deworming), "
            "breeding dates, calving/lambing/kidding records, and disposition (sold, died, culled with reason). "
            "HERD/FLOCK RECORDS: Total inventory by class (cows, calves, bulls, heifers), birth rate, "
            "weaning rate and average weight, death loss percentage, feed costs per animal, "
            "veterinary costs per animal, and revenue per animal. "
            "FINANCIAL RECORDS: Feed purchases and costs, veterinary expenses, fencing and infrastructure, "
            "equipment and maintenance, labor, marketing costs, and sales income by category. "
            "Track cost per pound of gain or cost per dozen eggs to evaluate profitability. "
            "TOOLS: Spreadsheets work for small operations. Specialized software includes CattleMax, EasyKeeper, "
            "Farmbrite, and Herdwatch. Many breed registries have online record systems. "
            "At minimum, maintain vaccination records (required for sales in many states) and financial records (required for taxes)."
        ),
        "metadata": {"doc_type": "guide", "animal_type": "All", "category": "farming", "use_case": "record_keeping"}
    },
    {
        "id": "guide_livestock_for_land_clearing",
        "content": (
            "Using Livestock for Weed and Brush Control. "
            "Livestock can be cheaper and more effective than mechanical or chemical brush control. "
            "GOATS are the premier brush-clearing animal. They prefer browse (woody plants, shrubs, weeds) over grass. "
            "A herd of 30 goats can clear 1 acre of heavy brush per month. They eat poison ivy, multiflora rose, "
            "kudzu, blackberry, and most invasive plants. Use temporary electric fencing to concentrate them on target areas. "
            "SHEEP eat broadleaf weeds, thistle, and leafy spurge but won't eat woody browse. "
            "They are excellent for maintaining cleared areas and controlling herbaceous weeds. "
            "CATTLE eat primarily grass and can be used to graze down tall weedy pastures before overseeding. "
            "Highland cattle and other hardy breeds will eat more brush than standard breeds. "
            "PIGS are excellent for clearing and tilling land. They root up stumps, eat roots, and turn soil. "
            "Use pigs to prepare garden beds or clear areas for pasture seeding. "
            "TARGETED GRAZING SERVICE: Some farmers offer contract grazing services to municipalities and landowners "
            "for vegetation management. This can be a profitable niche with rates of $500-1,500 per acre. "
            "Goat rental for weed control has become popular in urban and suburban areas for managing parks and rights-of-way."
        ),
        "metadata": {"doc_type": "guide", "animal_type": "All", "category": "use_case", "use_case": "land_clearing"}
    },
    {
        "id": "guide_direct_marketing",
        "content": (
            "Direct-to-Consumer Livestock Marketing. "
            "Selling directly to consumers typically returns 2-3x the price of selling through commodity markets. "
            "FARMERS MARKETS: Best for eggs, poultry, and value-added products (jerky, cheese, soap). "
            "Apply early as competitive markets have waiting lists. Budget for booth fee ($25-75/week), insurance, "
            "signage, and coolers. Build a customer base with consistent quality and availability. "
            "FREEZER BEEF/PORK/LAMB: Sell whole, half, or quarter animals direct to consumers. "
            "Customer pays processing costs separately. Requires USDA-inspected or state-inspected processing. "
            "Build a waiting list through word of mouth and social media. "
            "ON-FARM SALES: Host farm visits and tours. Farm-to-table events build community and sales. "
            "Egg stands and self-serve farm stores work well in rural areas. "
            "RESTAURANTS AND CHEFS: Premium market that values consistency and quality. "
            "Offer samples and delivery. Smaller, independent restaurants are more receptive than chains. "
            "ONLINE: Website with ordering for pickup or local delivery. "
            "Platforms like Local Harvest, Eat Wild, and Barn2Door connect farmers with consumers. "
            "PRICING: Research local retail prices and price at 70-80% of retail equivalent. "
            "Factor in ALL costs including labor, processing, and marketing. Don't underprice; "
            "premium direct-sale products should command premium prices."
        ),
        "metadata": {"doc_type": "guide", "animal_type": "All", "category": "use_case", "use_case": "marketing"}
    },
    {
        "id": "guide_emergency_preparedness",
        "content": (
            "Emergency Preparedness for Livestock Farms. "
            "NATURAL DISASTERS: Have an evacuation plan for livestock before disasters strike. "
            "Identify safe areas on your property (high ground for floods, clear areas for fire). "
            "Pre-arrange trailer access and evacuation routes. Maintain current animal inventory with photos for insurance. "
            "FIRE: Create defensible space around barns (30+ feet cleared). Store hay away from electrical sources. "
            "Install fire extinguishers in all buildings. Never store gasoline in livestock buildings. "
            "Practice barn evacuation with animals. Animals may resist leaving a burning barn; "
            "use halters or lead animals can follow. "
            "FLOOD: Move animals to high ground before water rises. Stock 3+ days of feed at elevation. "
            "After flooding, test water sources for contamination. Watch for leptospirosis in standing water. "
            "EXTREME WEATHER: Maintain 2-week feed reserve. Have a backup water source "
            "(generator for well pump, or stored water). Build relationships with neighboring farms for mutual aid. "
            "DISEASE OUTBREAK: Isolate sick animals immediately. Contact your veterinarian. "
            "Restrict visitor access. Clean and disinfect equipment between groups. "
            "Report notifiable diseases (foreign animal diseases, avian influenza) to state veterinarian immediately. "
            "INSURANCE: Livestock mortality insurance covers death from accident and disease. "
            "Pasture/rangeland/forage insurance covers feed losses from drought."
        ),
        "metadata": {"doc_type": "guide", "animal_type": "All", "category": "use_case", "use_case": "emergency_preparedness"}
    },
]


# ============================================================================
# BATCH EMBEDDING GENERATOR
# ============================================================================

def generate_embeddings_batched(emb_client, documents, batch_size=20):
    """Generate embeddings in batches with rate limiting and retry."""
    all_embeddings = []
    total = len(documents)

    for i in range(0, total, batch_size):
        batch = documents[i:i + batch_size]
        texts = [doc["content"] for doc in batch]

        for attempt in range(3):
            try:
                batch_embeddings = emb_client.embed_documents(texts)
                all_embeddings.extend(batch_embeddings)
                done = min(i + batch_size, total)
                print(f"  Embedded {done}/{total} ({done * 100 // total}%)")
                break
            except Exception as e:
                if "429" in str(e) or "quota" in str(e).lower():
                    wait = 2 ** attempt * 5
                    print(f"  Rate limited, waiting {wait}s...")
                    time.sleep(wait)
                else:
                    raise

        if i + batch_size < total:
            time.sleep(1)

    return all_embeddings


# ============================================================================
# FIRESTORE WRITER
# ============================================================================

def write_to_firestore(fs_client, collection_name, documents, embeddings):
    """Write documents with embeddings to Firestore in batches of 500."""
    BATCH_LIMIT = 500
    total = len(documents)
    written = 0
    collection_ref = fs_client.collection(collection_name)

    for i in range(0, total, BATCH_LIMIT):
        batch = fs_client.batch()
        chunk_docs = documents[i:i + BATCH_LIMIT]
        chunk_embs = embeddings[i:i + BATCH_LIMIT]

        for doc, emb in zip(chunk_docs, chunk_embs):
            doc_ref = collection_ref.document(doc["id"])
            batch.set(doc_ref, {
                "content": doc["content"],
                "embedding": Vector(emb),
                "metadata": doc["metadata"],
            })

        batch.commit()
        written += len(chunk_docs)
        print(f"  Written {written}/{total}")

    return written


def clear_collection(fs_client, collection_name):
    """Delete all documents in a collection."""
    collection_ref = fs_client.collection(collection_name)
    deleted = 0
    while True:
        docs = list(collection_ref.limit(100).stream())
        if not docs:
            break
        batch = fs_client.batch()
        for doc in docs:
            batch.delete(doc.reference)
        batch.commit()
        deleted += len(docs)
        print(f"  Deleted {deleted} documents...")
    return deleted


# ============================================================================
# MAIN ORCHESTRATOR
# ============================================================================

def main(force_rebuild=False, dry_run=False, skip_sql=False, skip_curated=False):
    print("=" * 60)
    print("Firestore RAG Seeder")
    print(f"  Database: {FIRESTORE_DATABASE}")
    print(f"  Collection: {FIRESTORE_COLLECTION}")
    print(f"  Embedding model: {EMBEDDING_MODEL}")
    print("=" * 60)

    # 1. Initialize clients
    print("\n[1/7] Initializing clients...")
    fs_client = get_firestore_client()
    print(f"  Firestore: connected to {FIRESTORE_DATABASE}")

    if not dry_run:
        emb_client = get_embeddings_client()
        print(f"  Embeddings: {EMBEDDING_MODEL}")

    # 2. Check existing documents
    print("\n[2/7] Checking existing collection...")
    collection_ref = fs_client.collection(FIRESTORE_COLLECTION)
    existing_docs = list(collection_ref.limit(1).stream())
    has_data = len(existing_docs) > 0

    if has_data:
        count_query = collection_ref.count()
        count_result = count_query.get()
        existing_count = count_result[0][0].value
        print(f"  Found {existing_count} existing documents")
    else:
        existing_count = 0
        print("  Collection is empty")

    if has_data and not force_rebuild:
        print("\n  Collection already has data. Use --force-rebuild to replace.")
        return

    # 3. Clear if rebuilding
    if force_rebuild and has_data:
        print("\n[3/7] Clearing existing documents...")
        clear_collection(fs_client, FIRESTORE_COLLECTION)
    else:
        print("\n[3/7] No clearing needed")

    # 4. Build document list
    print("\n[4/7] Building document list...")
    all_documents = []

    if not skip_sql:
        species_docs, breed_docs = extract_sql_data()
        all_documents.extend(species_docs)
        all_documents.extend(breed_docs)
        print(f"  SQL: {len(species_docs)} species + {len(breed_docs)} breeds")
    else:
        print("  SQL: skipped")

    if not skip_curated:
        all_documents.extend(CURATED_ARTICLES)
        print(f"  Curated: {len(CURATED_ARTICLES)} articles")
    else:
        print("  Curated: skipped")

    print(f"  Total: {len(all_documents)} documents")

    if not all_documents:
        print("\n  No documents to seed. Exiting.")
        return

    if dry_run:
        print("\n  DRY RUN - would write these documents:")
        for doc in all_documents[:10]:
            print(f"    [{doc['id']}] {doc['content'][:80]}...")
        if len(all_documents) > 10:
            print(f"    ... and {len(all_documents) - 10} more")
        return

    # 5. Generate embeddings
    print(f"\n[5/7] Generating embeddings (batch_size=20)...")
    start = time.time()
    embeddings = generate_embeddings_batched(emb_client, all_documents, batch_size=20)
    elapsed = time.time() - start
    print(f"  Done in {elapsed:.1f}s")

    # 6. Validate
    print(f"\n[6/7] Validating...")
    assert len(embeddings) == len(all_documents), \
        f"Mismatch: {len(embeddings)} embeddings for {len(all_documents)} documents"
    dim = len(embeddings[0])
    print(f"  {len(embeddings)} embeddings, {dim} dimensions each")

    # 7. Write to Firestore
    print(f"\n[7/7] Writing to Firestore...")
    start = time.time()
    written = write_to_firestore(fs_client, FIRESTORE_COLLECTION, all_documents, embeddings)
    elapsed = time.time() - start
    print(f"  Done: {written} documents in {elapsed:.1f}s")

    # Verify
    print("\n" + "=" * 60)
    print("VERIFICATION")
    print("=" * 60)
    verify_docs = list(collection_ref.limit(1).stream())
    if verify_docs:
        count_result = collection_ref.count().get()
        final_count = count_result[0][0].value
        print(f"  Documents in collection: {final_count}")
    else:
        print("  WARNING: Collection appears empty after write!")

    # Test search
    print("\n  Test search: 'best dairy cattle breed for small farm'")
    try:
        test_emb = emb_client.embed_query("best dairy cattle breed for small farm")
        test_results = collection_ref.find_nearest(
            vector_field="embedding",
            query_vector=Vector(test_emb),
            distance_measure=DistanceMeasure.COSINE,
            limit=3,
        ).get()
        for i, doc in enumerate(test_results, 1):
            data = doc.to_dict()
            print(f"    {i}. {data.get('content', '')[:100]}...")
    except Exception as e:
        print(f"  Test search failed (index may not be ready yet): {e}")
        print("  Create the vector index, wait for it to be READY, then test again.")

    print("\n  NEXT STEP: Create the vector index if not already done:")
    print("  gcloud firestore indexes composite create \\")
    print(f"    --project={GCP_PROJECT} \\")
    print(f"    --database={FIRESTORE_DATABASE} \\")
    print(f"    --collection-group={FIRESTORE_COLLECTION} \\")
    print("    --field-config=vector-config='{\"dimension\":\"768\",\"flat\":{}}',field-path=embedding")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed Firestore livestock_knowledge collection for RAG")
    parser.add_argument("--force-rebuild", action="store_true",
                        help="Delete existing documents and rebuild from scratch")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview what would be done without writing")
    parser.add_argument("--skip-sql", action="store_true",
                        help="Skip SQL Server data extraction")
    parser.add_argument("--skip-curated", action="store_true",
                        help="Skip curated knowledge articles")
    args = parser.parse_args()

    main(
        force_rebuild=args.force_rebuild,
        dry_run=args.dry_run,
        skip_sql=args.skip_sql,
        skip_curated=args.skip_curated,
    )
