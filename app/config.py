import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parent.parent
RULEBOOKS_DIR = ROOT_DIR / "rulebooks"
MASTERLIST_CSV = ROOT_DIR / "masterlist" / "boardgames_ranks.csv"
GAMES_CSV = ROOT_DIR / "masterlist" / "games.csv"
BGG_DB_CSV = ROOT_DIR / "masterlist" / "bgg_db_2018_01.csv"
BGG_DATASET_CSV = ROOT_DIR / "masterlist" / "BGG_Data_Set.csv"
CACHE_DIR = ROOT_DIR / "data" / "cache"

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
CHAT_MODEL = os.environ.get("CHAT_MODEL", "gpt-4o-mini")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")
# Matches the existing "board-game-concierge" Pinecone index's configured
# dimension. text-embedding-3-small natively outputs 1536 dims but supports
# truncating via the `dimensions` param, so this doesn't require recreating
# the index.
EMBEDDING_DIMENSIONS = 512

PINECONE_API_KEY = os.environ.get("PINECONE_API_KEY", "")
PINECONE_INDEX_NAME = os.environ.get("PINECONE_INDEX_NAME", "board-game-concierge")
PINECONE_CLOUD = os.environ.get("PINECONE_CLOUD", "aws")
PINECONE_REGION = os.environ.get("PINECONE_REGION", "us-east-1")

SERP_API_KEY = os.environ.get("SERP_API_KEY", "")
SERPER_API_KEY = os.environ.get("SERPER_API_KEY", "")
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")

# Cosine-similarity floor (index uses metric="cosine", see ingest.py) below
# which a retrieved chunk is treated as noise rather than grounding - if
# every chunk for a query falls below this, the endpoint says "I don't have
# that" instead of asking the LLM to write from a near-empty/irrelevant
# excerpt. 0.3 is an untested starting guess, not a calibrated value - tune
# it against real query/rulebook score distributions once there's a live
# index to test against (log scores for a while and see where true-positive
# vs. true-negative chunks actually land before trusting this number).
RAG_MIN_SCORE = float(os.environ.get("RAG_MIN_SCORE", "0.3"))

# Full rulebook library - every PDF in rulebooks/, each mapped to a BGG ID.
# bgg_id is deliberately the exact ID app/clients/game_lookup.py's
# _load_index() would resolve that game's name to (verified against
# masterlist/boardgames_ranks.csv, not guessed) - a mismatch there means
# resolve_game() finds the row but PILOT_GAMES_BY_BGG_ID.get() misses it,
# so the bot claims not to know a game it actually has a rulebook for.
PILOT_GAMES = [
    {
        "slug": "ticket-to-ride",
        "name": "Ticket to Ride",
        "bgg_id": "9209",
        "rulebook_file": "Ticket-To-ride.pdf",
    },
    {
        "slug": "catan-seafarers",
        "name": "Catan: Seafarers",
        "bgg_id": "325",
        "rulebook_file": "CATAN-Seafarers-rules-mayfair-1.pdf",
    },
    {
        "slug": "3-ring-circus",
        "name": "3 Ring Circus",
        "bgg_id": "371947",
        "rulebook_file": "3 Ring Circus_Rulebook_ENG_v2_baja.pdf",
    },
    {
        "slug": "azul",
        "name": "Azul",
        "bgg_id": "230802",
        "rulebook_file": "Azul-Rules.pdf",
    },
    {
        "slug": "catan-treasures-dragons-adventurers",
        "name": "Catan: Treasures, Dragons & Adventurers",
        "bgg_id": "56157",
        "rulebook_file": "Catan-Treasure-Dragons-and-Adventurers-Rulebook_210107-sm.pdf",
    },
    {
        "slug": "game-of-thrones",
        "name": "A Game of Thrones: The Board Game (Second Edition)",
        "bgg_id": "103343",
        "rulebook_file": "GameOfThrones_rulebook_web.pdf",
    },
    # "Hive" (Hive_English_Rules.pdf) is deliberately excluded - it's a
    # scanned/image-only PDF (12 pages, each just one embedded image, zero
    # extractable text) and this pipeline has no OCR step, so there's
    # nothing for parse_pdf.py to chunk. Needs a text-layer PDF (or OCR
    # support added) before it can be added back.
    {
        "slug": "memoir-44",
        "name": "Memoir '44",
        "bgg_id": "10630",
        "rulebook_file": "Memoir44_v4.1_rulebook.pdf",
    },
    {
        "slug": "monopoly",
        "name": "Monopoly",
        "bgg_id": "1406",
        "rulebook_file": "Monopoly.pdf",
    },
    {
        "slug": "sequence",
        "name": "Sequence",
        "bgg_id": "2375",
        "rulebook_file": "Sequence-Instructions.pdf",
    },
    # "Stratego" (Stratego.pdf) is deliberately excluded for the same reason
    # - scanned/image-only PDF (6 pages, one embedded image each, zero
    # extractable text), no OCR step in this pipeline.
    {
        "slug": "terraforming-mars",
        "name": "Terraforming Mars",
        "bgg_id": "167791",
        "rulebook_file": "Terraforming-mars-rulebook.pdf",
    },
    {
        "slug": "tripoley",
        "name": "Tripoley",
        "bgg_id": "4853",
        "rulebook_file": "Tripoley-Instructions.pdf",
    },
    {
        "slug": "wingspan",
        "name": "Wingspan",
        "bgg_id": "266192",
        "rulebook_file": "Wingspan-Instructions.pdf",
    },
    {
        "slug": "catan-cities-knights",
        "name": "Catan: Cities & Knights",
        "bgg_id": "926",
        "rulebook_file": "catan-cities-knights-rulebook.pdf",
    },
    {
        "slug": "catan-explorers-pirates",
        "name": "Catan: Explorers & Pirates",
        "bgg_id": "135378",
        "rulebook_file": "catan-explorers-pirates-rulebook.pdf",
    },
    {
        "slug": "catan-traders-barbarians",
        "name": "Catan: Traders & Barbarians",
        "bgg_id": "27760",
        "rulebook_file": "catan-traders-barbarians-rulebook-1.pdf",
    },
    {
        "slug": "jaipur",
        "name": "Jaipur",
        "bgg_id": "54043",
        "rulebook_file": "jaipur.pdf",
    },
    {
        "slug": "risk",
        "name": "Risk",
        "bgg_id": "181",
        "rulebook_file": "risk-Instructions.pdf",
    },
]

PILOT_GAMES_BY_BGG_ID = {game["bgg_id"]: game for game in PILOT_GAMES}
