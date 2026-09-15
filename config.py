"""Edit this file before running the bot."""



import os

from pathlib import Path



# Keep secrets out of git. Set BOT_TOKEN in the deployment environment.

BOT_TOKEN = os.getenv("BOT_TOKEN", "")

GITHUB_TOKEN_ENV_NAME = "GITHUB_TOKEN"

DATA_REPO = "shadow667788/PremiumPostMakerData"

DATA_BRANCH = "main"

USER_DATA_PATH = "skx/users"

META_DATA_PATH = "skx/meta.json"

BOT_USERNAME = "@TxGencrypt_filebot"

OWNER_IDS = {7441729576, 8265449911}



# Membership checks require chat handles, while buttons use the derived t.me links.

REQUIRED_CHANNELS = [
    
    "@itxtalhabrand",
    
    "@bilal_king_vip",
    
    "@BXTOTPCHANNEL",
    
    "@tgfreeinternet",
    
    "@sk_dev_official",
    
    "@shadowhacrrrr",
    
]

REQUIRED_CHANNEL_LABELS = [
    
    "@itxtalhabrand",
    
    "@bilal_king_vip",
    
    "@BXTOTPCHANNEL",
    
    "@tgfreeinternet",
    
    "@sk_dev_official",
    
    "@shadowhacrrrr",
    
]

REQUIRED_PRIVATE_CHAT_ID = -1003899675817

REQUIRED_PRIVATE_INVITE_LINK = "https://t.me/+rerBRpmbTCs4MGY0"

REQUIRED_CHAT_IDS = REQUIRED_CHANNELS

PRIVATE_CHAT_ID = REQUIRED_PRIVATE_CHAT_ID

MEMBERSHIP_GATE_ENABLED = false

DB_PATH = Path(__file__).with_name("skx_talha.sqlite3")

MAX_DESTINATIONS_PER_POST = 20

BRAND = "SK X TALHA PREMIUM POST MAKER"

EMOJI_POOL_VERSION = 2

BANNER_URL = "https://i.postimg.cc/KYw0S3Tx/file-00000000cb2c82118de4bf959f94407f.png"















