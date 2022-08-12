from urllib.request import Request
from sqlalchemy import true
import api.middleware
import api.database.functions as functions
from api.config import app, redis_client
import logging
from fastapi_utils.tasks import repeat_every

logger = logging.getLogger(__name__)


@app.on_event("startup")
@repeat_every(seconds=5, wait_first=True, raise_exceptions=True)
async def automated_tasks():
    try:
        await functions.post_worlds()
        logger.info(f"Automated tasks finished.")

    except Exception as e:
        logger.warning(e)
        logger.info(f"Automated tasks have failed.")
        pass


@app.on_event("startup")
@repeat_every(seconds=3600, raise_exceptions=True)
async def ban_collection():
    try:
        await functions.get_wdr_bans()
        await functions.get_runewatch_bans()
        logger.info(f"Ban collection finished.")
    except Exception as e:
        logger.warning(e)
        logger.info(f"Ban collection has failed.")
        pass


@app.on_event("startup")
async def redis_health_check():
    if await redis_client.ping():
        logging.info("REDIS SERVER CONNECTED!")
    else:
        logging.critical("REDIS SERVER IS NOT ACCESSIBLE!")


@app.get("/")
async def root():
    return {
        "message": "Welcome to the NeverScapeAlone-matchmaker! If you're interested in becoming a developer, please contact ferrariictweet@gmail.com!"
    }
