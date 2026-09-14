"""Edit this file before running the bot."""
import os
from pathlib import Path

BOT_TOKEN = os.getenv("BOT_TOKEN", "PUT_BOT_TOKEN_HERE")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")
BOT_USERNAME = "@your_bot_username"
OWNER_IDS = {7441729576, 8265449911}
# Existing owners are allowed to add/remove secondary owners at runtime.
REQUIRED_CHANNELS = [
    "@itxtalhabrand",
    "@bilal_king_vip",
    "@BXTOTPCHANNEL",
    "@tgfreeinternet",
    "https://t.me/sk_dev_official",
    "https://t.me/shadowhacrrrr",
]
REQUIRED_PRIVATE_CHAT_ID = -1003899675817
DB_PATH = Path(__file__).with_name("skx_talha.sqlite3")
MAX_DESTINATIONS_PER_POST = 20
BRAND = "SK X TALHA PERIMUIM POST MAKER"
