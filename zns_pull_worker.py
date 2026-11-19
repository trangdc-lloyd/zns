import time
from datetime import datetime

from zns_processor import build_logger, load_config, process_ready_rows


NIGHT_START_HOUR = 0
NIGHT_END_HOUR = 6
NIGHT_POLL_INTERVAL_SEC = 120


def get_current_poll_interval(config):
    current_hour = datetime.now().hour
    if NIGHT_START_HOUR <= current_hour < NIGHT_END_HOUR:
        return NIGHT_POLL_INTERVAL_SEC

    return int(config["poll_interval_sec"])


def run_forever():
    logger = build_logger()
    config = load_config(logger=logger)
    default_interval = int(config["poll_interval_sec"])
    logger.info(
        "Starting pull worker with default poll interval %s seconds. Night interval is %s seconds from 00:00 to 06:00.",
        default_interval,
        NIGHT_POLL_INTERVAL_SEC,
    )

    while True:
        try:
            summary = process_ready_rows(logger=logger)
            logger.info("Cycle completed: %s", summary)
        except Exception:
            logger.exception("Cycle failed")

        interval = get_current_poll_interval(config)
        logger.info("Sleeping %s seconds before next cycle", interval)
        time.sleep(interval)


if __name__ == "__main__":
    run_forever()