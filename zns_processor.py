import json
import logging
from pathlib import Path

import gspread
import requests


CONFIG_PATH = Path(__file__).with_name("zns_pull_config.json")
STATE_PATH = Path(__file__).with_name("zns_pull_state.json")
STATUS_READY = "Sẵn sàng"
STATUS_SENT = "Đã gửi"


def build_logger():
    logger = logging.getLogger("zns_pull")
    if logger.handlers:
        return logger

    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s %(message)s",
    )
    return logger


def load_config(logger=None):
    logger = logger or build_logger()
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Missing config file: {CONFIG_PATH}. Create it from zns_pull_config.example.json"
        )

    with CONFIG_PATH.open("r", encoding="utf-8") as handle:
        config = json.load(handle)

    required_keys = [
        "service_account_json",
        "spreadsheet_id",
        "sheet_name",
        "zns_endpoint",
        "zns_auth_key",
        "zns_from",
        "zns_template_id",
    ]
    missing_keys = [key for key in required_keys if not config.get(key)]
    if missing_keys:
        raise ValueError(f"Missing config keys: {', '.join(missing_keys)}")

    config.setdefault("status_col", 25)
    config.setdefault("client_req_id_col", 26)
    config.setdefault("data_start_row", 2)
    config.setdefault("request_timeout_sec", 30)
    config.setdefault("poll_interval_sec", 60)
    config.setdefault("max_sanphamua_length", 200)
    config.setdefault("lookback_rows", 100)
    config.setdefault("full_scan_interval_cycles", 60)

    logger.info(
        "Loaded config for sheet '%s' in spreadsheet '%s'",
        config["sheet_name"],
        config["spreadsheet_id"],
    )
    return config


def open_sheet(config, logger=None):
    logger = logger or build_logger()
    logger.info("Opening sheet '%s'", config["sheet_name"])
    client = gspread.service_account_from_dict(config["service_account_json"])
    spreadsheet = client.open_by_key(config["spreadsheet_id"])
    return spreadsheet.worksheet(config["sheet_name"])


def load_state(config, logger=None):
    logger = logger or build_logger()
    default_state = {
        "last_sheet_row": config["data_start_row"] - 1,
        "cycles_since_full_scan": 0,
    }

    if not STATE_PATH.exists():
        logger.info("State file not found. Starting with a full scan.")
        return default_state

    try:
        with STATE_PATH.open("r", encoding="utf-8") as handle:
            saved_state = json.load(handle)
    except Exception:
        logger.exception("Could not read state file. Starting with a full scan.")
        return default_state

    state = {
        "last_sheet_row": int(
            saved_state.get("last_sheet_row", default_state["last_sheet_row"])
        ),
        "cycles_since_full_scan": int(
            saved_state.get(
                "cycles_since_full_scan", default_state["cycles_since_full_scan"]
            )
        ),
    }
    return state


def save_state(state, logger=None):
    logger = logger or build_logger()
    with STATE_PATH.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2)
    logger.info("Saved scan state: %s", state)


def detect_last_row(sheet, config, logger=None):
    logger = logger or build_logger()
    first_column_values = sheet.col_values(1)
    last_row = max(len(first_column_values), config["HEADER_ROW"] if "HEADER_ROW" in config else 1)
    logger.info("Detected last used row: %s", last_row)
    return last_row


def should_do_full_scan(state, last_row, config):
    if state["last_sheet_row"] < config["data_start_row"]:
        return True
    if last_row < state["last_sheet_row"]:
        return True
    return state["cycles_since_full_scan"] >= int(config["full_scan_interval_cycles"])


def get_scan_start_row(state, last_row, config, full_scan):
    if full_scan:
        return config["data_start_row"]

    lookback_rows = max(int(config["lookback_rows"]), 1)
    scan_start_row = max(
        config["data_start_row"],
        min(state["last_sheet_row"], last_row) - lookback_rows + 1,
    )
    return scan_start_row


def digits_only(value):
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def to_zns_phone(value):
    digits = digits_only(value)
    if not digits:
        return ""
    if digits.startswith("84") and len(digits) >= 11:
        return digits
    if digits.startswith("0") and len(digits) >= 10:
        return "84" + digits[1:]
    if len(digits) == 9:
        return "84" + digits
    return ""


def to_local_phone(value):
    digits = digits_only(value)
    if not digits:
        return ""
    if digits.startswith("0") and len(digits) >= 10:
        return digits
    if digits.startswith("84") and len(digits) >= 11:
        return "0" + digits[2:]
    if len(digits) == 9:
        return "0" + digits
    return ""


def build_address(row):
    parts = [row[10], row[8], row[7], row[6]]
    return ", ".join(str(part).strip() for part in parts if str(part).strip())


def limit_text(value, max_length, field_name, logger=None):
    logger = logger or build_logger()
    text = str(value).strip()
    if len(text) <= max_length:
        return text

    shortened = text[:max_length].rstrip()
    logger.info(
        "Field %s exceeded maxLength=%s. Truncated from %s to %s characters.",
        field_name,
        max_length,
        len(text),
        len(shortened),
    )
    return shortened


def build_payload(row, client_req_id, config, logger=None):
    raw_phone = row[3]
    to_phone = to_zns_phone(raw_phone)
    local_phone = to_local_phone(raw_phone)
    product_name = limit_text(
        row[11], config["max_sanphamua_length"], "sanphamua", logger=logger
    )
    if not to_phone or not local_phone:
        raise ValueError("Sdt khong hop le")

    payload = {
        "from": str(config["zns_from"]),
        "to": to_phone,
        "template_id": str(config["zns_template_id"]),
        "client_req_id": str(client_req_id),
        "template_data": {
            "hoten": str(row[1]).strip(),
            "sdt": local_phone,
            "dia_chi": build_address(row),
            "sanphamua": product_name,
        },
    }

    required_fields = payload["template_data"]
    if not all(required_fields.values()):
        raise ValueError("Thieu du 4 truong template_data")

    return payload


def send_zns(payload, config, logger=None):
    logger = logger or build_logger()
    logger.info("----- ZNS SEND START -----")
    logger.info(
        "Sending ZNS client_req_id=%s to=%s template_id=%s",
        payload["client_req_id"],
        payload["to"],
        payload["template_id"],
    )
    logger.info("Endpoint: %s", config["zns_endpoint"])
    logger.info("Request payload: %s", json.dumps(payload, ensure_ascii=False))

    response = requests.post(
        config["zns_endpoint"],
        json=payload,
        headers={
            "Authorization": config["zns_auth_key"],
            "Content-Type": "application/json",
        },
        timeout=config["request_timeout_sec"],
    )
    logger.info("HTTP status: %s", response.status_code)
    logger.info("Response body: %s", response.text)
    logger.info("----- ZNS SEND END -----")
    response.raise_for_status()
    return response.json()


def update_status(sheet, row_number, status_col, status, logger=None):
    logger = logger or build_logger()
    logger.info("Updating row %s status -> %s", row_number, status)
    sheet.update_cell(row_number, status_col, status)


def process_ready_rows(logger=None):
    logger = logger or build_logger()
    config = load_config(logger=logger)
    sheet = open_sheet(config, logger=logger)
    state = load_state(config, logger=logger)
    last_row = detect_last_row(sheet, config, logger=logger)
    logger.info("Loaded metadata for sheet with last row %s", last_row)
    if last_row < config["data_start_row"]:
        logger.info("No data rows found")
        save_state(
            {
                "last_sheet_row": config["data_start_row"] - 1,
                "cycles_since_full_scan": 0,
            },
            logger=logger,
        )
        return {"processed": 0, "ready_rows": [], "sent": 0, "failed": 0}

    full_scan = should_do_full_scan(state, last_row, config)
    scan_start_row = get_scan_start_row(state, last_row, config, full_scan)
    logger.info(
        "Scan strategy: %s scan from row %s to row %s",
        "full" if full_scan else "tail",
        scan_start_row,
        last_row,
    )

    row_count = last_row - scan_start_row + 1
    values = sheet.get(f"A{scan_start_row}:Z{last_row}")
    logger.info("Loaded %s row(s) from sheet for this cycle", len(values))
    if row_count > len(values):
        values.extend([[""] * config["client_req_id_col"] for _ in range(row_count - len(values))])

    ready_rows = []
    for index, row in enumerate(values):
        row_number = scan_start_row + index
        if len(row) < config["client_req_id_col"]:
            row = row + [""] * (config["client_req_id_col"] - len(row))

        status = str(row[config["status_col"] - 1]).strip()
        if status == STATUS_READY:
            ready_rows.append(row_number)

    if not ready_rows:
        logger.info("No rows with status Sẵn sàng")
        save_state(
            {
                "last_sheet_row": last_row,
                "cycles_since_full_scan": 0 if full_scan else state["cycles_since_full_scan"] + 1,
            },
            logger=logger,
        )
        return {"processed": 0, "ready_rows": [], "sent": 0, "failed": 0}

    logger.info("Found %s row(s) ready to send: %s", len(ready_rows), ready_rows)

    processed = 0
    sent = 0
    failed = 0

    for row_number in ready_rows:
        row = values[row_number - scan_start_row]
        if len(row) < config["client_req_id_col"]:
            row = row + [""] * (config["client_req_id_col"] - len(row))

        client_req_id = str(row[config["client_req_id_col"] - 1]).strip()
        if not client_req_id:
            logger.info("Row %s is missing client_req_id", row_number)
            update_status(
                sheet,
                row_number,
                config["status_col"],
                "LOI: thieu client_req_id",
                logger=logger,
            )
            processed += 1
            failed += 1
            continue

        try:
            logger.info("Processing row %s", row_number)
            payload = build_payload(row, client_req_id, config, logger=logger)
            result = send_zns(payload, config, logger=logger)
            if int(result.get("status", 0)) == 1:
                tracking_id = result.get("tracking_id", "")
                logger.info(
                    "Row %s sent successfully tracking_id=%s", row_number, tracking_id
                )
                update_status(
                    sheet,
                    row_number,
                    config["status_col"],
                    STATUS_SENT,
                    logger=logger,
                )
                sent += 1
            else:
                error_code = result.get("errorcode", "unknown")
                description = result.get("description", "Unknown error")
                logger.info(
                    "Row %s failed error_code=%s description=%s",
                    row_number,
                    error_code,
                    description,
                )
                update_status(
                    sheet,
                    row_number,
                    config["status_col"],
                    f"LOI: {error_code} - {description}",
                    logger=logger,
                )
                failed += 1
        except Exception as exc:
            logger.exception("Row %s raised exception", row_number)
            update_status(
                sheet,
                row_number,
                config["status_col"],
                f"LOI: {exc}",
                logger=logger,
            )
            failed += 1

        processed += 1

    save_state(
        {
            "last_sheet_row": last_row,
            "cycles_since_full_scan": 0 if full_scan else state["cycles_since_full_scan"] + 1,
        },
        logger=logger,
    )
    logger.info("Finished processing %s row(s)", processed)
    return {
        "processed": processed,
        "ready_rows": ready_rows,
        "sent": sent,
        "failed": failed,
    }


def main():
    logger = build_logger()
    logger.info("Starting one-shot zns_pull processing")
    summary = process_ready_rows(logger=logger)
    logger.info("One-shot processing summary: %s", summary)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()