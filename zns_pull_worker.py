import time

from zns_processor import build_logger, load_config, process_ready_rows


def run_forever():
    logger = build_logger()
    config = load_config(logger=logger)
    interval = int(config["poll_interval_sec"])
    logger.info("Starting pull worker with poll interval %s seconds", interval)

    while True:
        try:
            summary = process_ready_rows(logger=logger)
            logger.info("Cycle completed: %s", summary)
        except Exception:
            logger.exception("Cycle failed")

        time.sleep(interval)


if __name__ == "__main__":
    run_forever()