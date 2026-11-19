import json
import logging
from pathlib import Path

import gspread
import requests


CONFIG_PATH = Path(__file__).with_name("zns_pull_config.json")
STATE_PATH = Path(__file__).with_name("zns_pull_state.json")
STATUS_READY = "Sẵn sàng"
STATUS_SENT = "Đã gửi"
STATUS_SKIPPED = "Bỏ qua"

DEFAULT_NAME_COL = 2
DEFAULT_PHONE_COL = 4
DEFAULT_ADDRESS_COLS = [11, 9, 8, 7]
DEFAULT_PRODUCT_COL = 12


def build_logger():
    logger = logging.getLogger("zns_pull")
    if logger.handlers:
        return logger

    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s %(message)s",
    )
    return logger


def normalize_source_config(raw_source, base_config, index=0):
    source = dict(base_config)
    source.update(raw_source)

    required_keys = [
        "service_account_json",
        "spreadsheet_id",
        "sheet_name",
        "zns_endpoint",
        "zns_auth_key",
        "zns_from",
        "zns_template_id",
    ]
    missing_keys = [key for key in required_keys if not source.get(key)]
    if missing_keys:
        raise ValueError(f"Missing config keys in source #{index + 1}: {', '.join(missing_keys)}")

    source.setdefault("id", f"source_{index + 1}")
    source.setdefault("status_col", 25)
    source.setdefault("client_req_id_col", 26)
    source.setdefault("name_col", DEFAULT_NAME_COL)
    source.setdefault("phone_col", DEFAULT_PHONE_COL)
    source.setdefault("address_cols", list(DEFAULT_ADDRESS_COLS))
    source.setdefault("product_col", DEFAULT_PRODUCT_COL)
    source.setdefault("allowed_products", [])
    source.setdefault("data_start_row", 2)
    source.setdefault("request_timeout_sec", 30)
    source.setdefault("poll_interval_sec", 60)
    source.setdefault("max_sanphamua_length", 200)
    source.setdefault("lookback_rows", 100)
    source.setdefault("full_scan_interval_cycles", 60)
    return source


def load_config(logger=None):
    logger = logger or build_logger()
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Missing config file: {CONFIG_PATH}. Create it from zns_pull_config.example.json"
        )

    with CONFIG_PATH.open("r", encoding="utf-8") as handle:
        config = json.load(handle)

    config.setdefault("request_timeout_sec", 30)
    config.setdefault("poll_interval_sec", 60)
    config.setdefault("max_sanphamua_length", 200)
    config.setdefault("lookback_rows", 100)
    config.setdefault("full_scan_interval_cycles", 60)

    raw_sources = config.get("sources")
    if raw_sources:
        if not isinstance(raw_sources, list):
            raise ValueError("Config key 'sources' must be a list")
        base_config = {k: v for k, v in config.items() if k != "sources"}
        sources = [
            normalize_source_config(raw_source, base_config, index=i)
            for i, raw_source in enumerate(raw_sources)
        ]
    else:
        sources = [normalize_source_config(config, {}, index=0)]

    config["sources"] = sources
    for source in sources:
        logger.info(
            "Loaded config [%s] for sheet '%s'",
            source["id"],
            source["sheet_name"],
        )
    return config


def open_sheet(config, logger=None, client=None):
    logger = logger or build_logger()
    logger.info("[%s] Opening sheet '%s'", config.get("id", "default"), config["sheet_name"])
    gspread_client = client or gspread.service_account_from_dict(config["service_account_json"])
    spreadsheet = gspread_client.open_by_key(config["spreadsheet_id"])
    return spreadsheet.worksheet(config["sheet_name"])


def col_to_letter(col_num):
    dividend = int(col_num)
    column_name = ""
    while dividend > 0:
        modulo = (dividend - 1) % 26
        column_name = chr(65 + modulo) + column_name
        dividend = (dividend - modulo) // 26
    return column_name


def load_all_states(logger=None):
    logger = logger or build_logger()
    if not STATE_PATH.exists():
        return {}

    try:
        with STATE_PATH.open("r", encoding="utf-8") as handle:
            saved_state = json.load(handle)
        return saved_state if isinstance(saved_state, dict) else {}
    except Exception:
        logger.exception("Could not read state file. Starting with a full scan.")
        return {}


def load_state(config, logger=None):
    logger = logger or build_logger()
    default_state = {
        "last_sheet_row": config["data_start_row"] - 1,
        "cycles_since_full_scan": 0,
    }

    saved_state = load_all_states(logger=logger)
    if not saved_state:
        logger.info("State file not found. Starting with a full scan for [%s].", config["id"])
        return default_state

    sources_state = saved_state.get("sources")
    if isinstance(sources_state, dict):
        source_state = sources_state.get(config["id"])
        if not isinstance(source_state, dict):
            logger.info("State not found for [%s]. Starting with a full scan.", config["id"])
            return default_state
    elif "last_sheet_row" in saved_state:
        # Backward-compatible migration from legacy single-source state format
        source_state = saved_state
    else:
        return default_state

    return {
        "last_sheet_row": int(
            source_state.get("last_sheet_row", default_state["last_sheet_row"])
        ),
        "cycles_since_full_scan": int(
            source_state.get(
                "cycles_since_full_scan", default_state["cycles_since_full_scan"]
            )
        ),
    }


def save_state(state, source_id, logger=None):
    logger = logger or build_logger()
    all_states = load_all_states(logger=logger)
    sources_state = all_states.get("sources")
    if not isinstance(sources_state, dict):
        sources_state = {}

    sources_state[source_id] = state
    payload = {"sources": sources_state}
    with STATE_PATH.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    logger.info("Saved scan state [%s]: %s", source_id, state)


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


def get_cell(row, col_1based):
    idx = int(col_1based) - 1
    if idx < 0 or idx >= len(row):
        return ""
    return row[idx]


def build_address(row, address_cols):
    parts = [get_cell(row, col) for col in address_cols]
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
    raw_phone = get_cell(row, config["phone_col"])
    to_phone = to_zns_phone(raw_phone)
    local_phone = to_local_phone(raw_phone)
    product_name = limit_text(
        get_cell(row, config["product_col"]),
        config["max_sanphamua_length"],
        "sanphamua",
        logger=logger,
    )
    if not to_phone or not local_phone:
        raise ValueError("Sdt khong hop le")

    payload = {
        "from": str(config["zns_from"]),
        "to": to_phone,
        "template_id": str(config["zns_template_id"]),
        "client_req_id": str(client_req_id),
        "template_data": {
            "hoten": str(get_cell(row, config["name_col"])).strip(),
            "sdt": local_phone,
            "dia_chi": build_address(row, config["address_cols"]),
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


def is_allowed_product(product_value, allowed_products):
    if not allowed_products:
        return True
    normalized = str(product_value or "").strip().lower()
    return any(keyword.lower() in normalized for keyword in allowed_products)


def process_source_ready_rows(config, logger=None, client=None):
    logger = logger or build_logger()
    source_id = config["id"]
    sheet = open_sheet(config, logger=logger, client=client)
    state = load_state(config, logger=logger)
    last_row = detect_last_row(sheet, config, logger=logger)
    logger.info("[%s] Loaded metadata for sheet with last row %s", source_id, last_row)
    if last_row < config["data_start_row"]:
        logger.info("[%s] No data rows found", source_id)
        save_state(
            {
                "last_sheet_row": config["data_start_row"] - 1,
                "cycles_since_full_scan": 0,
            },
            source_id,
            logger=logger,
        )
        return {"source_id": source_id, "processed": 0, "ready_rows": [], "sent": 0, "failed": 0, "skipped": 0}

    full_scan = should_do_full_scan(state, last_row, config)
    scan_start_row = get_scan_start_row(state, last_row, config, full_scan)
    logger.info(
        "[%s] Scan strategy: %s scan from row %s to row %s",
        source_id,
        "full" if full_scan else "tail",
        scan_start_row,
        last_row,
    )

    max_col = max(
        [
            int(config["status_col"]),
            int(config["client_req_id_col"]),
            int(config["name_col"]),
            int(config["phone_col"]),
            int(config["product_col"]),
            *[int(c) for c in config["address_cols"]],
        ]
    )
    end_col_letter = col_to_letter(max_col)
    row_count = last_row - scan_start_row + 1
    values = sheet.get(f"A{scan_start_row}:{end_col_letter}{last_row}")
    logger.info("[%s] Loaded %s row(s) from sheet for this cycle", source_id, len(values))
    if row_count > len(values):
        values.extend([[""] * max_col for _ in range(row_count - len(values))])

    ready_rows = []
    for index, row in enumerate(values):
        row_number = scan_start_row + index
        if len(row) < max_col:
            row = row + [""] * (max_col - len(row))
            values[index] = row

        status = str(get_cell(row, config["status_col"])).strip()
        if status == STATUS_READY:
            ready_rows.append(row_number)

    if not ready_rows:
        logger.info("[%s] No rows with status Sẵn sàng", source_id)
        save_state(
            {
                "last_sheet_row": last_row,
                "cycles_since_full_scan": 0 if full_scan else state["cycles_since_full_scan"] + 1,
            },
            source_id,
            logger=logger,
        )
        return {"source_id": source_id, "processed": 0, "ready_rows": [], "sent": 0, "failed": 0, "skipped": 0}

    logger.info("[%s] Found %s row(s) ready to send: %s", source_id, len(ready_rows), ready_rows)

    allowed_products = [str(p).strip() for p in config.get("allowed_products", []) if str(p).strip()]
    processed = 0
    sent = 0
    failed = 0
    skipped = 0

    for row_number in ready_rows:
        row = values[row_number - scan_start_row]

        if allowed_products:
            product_value = str(get_cell(row, config["product_col"])).strip()
            if not is_allowed_product(product_value, allowed_products):
                logger.info(
                    "[%s] Row %s product '%s' is not in allowed_products %s. Marking '%s'.",
                    source_id,
                    row_number,
                    product_value,
                    allowed_products,
                    STATUS_SKIPPED,
                )
                update_status(
                    sheet,
                    row_number,
                    config["status_col"],
                    STATUS_SKIPPED,
                    logger=logger,
                )
                processed += 1
                skipped += 1
                continue

        client_req_id = str(get_cell(row, config["client_req_id_col"])).strip()
        if not client_req_id:
            logger.info("[%s] Row %s is missing client_req_id", source_id, row_number)
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
            logger.info("[%s] Processing row %s", source_id, row_number)
            payload = build_payload(row, client_req_id, config, logger=logger)
            result = send_zns(payload, config, logger=logger)
            if int(result.get("status", 0)) == 1:
                tracking_id = result.get("tracking_id", "")
                logger.info(
                    "[%s] Row %s sent successfully tracking_id=%s", source_id, row_number, tracking_id
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
                    "[%s] Row %s failed error_code=%s description=%s",
                    source_id,
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
            logger.exception("[%s] Row %s raised exception", source_id, row_number)
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
        source_id,
        logger=logger,
    )
    logger.info("[%s] Finished processing %s row(s)", source_id, processed)
    return {
        "source_id": source_id,
        "processed": processed,
        "ready_rows": ready_rows,
        "sent": sent,
        "failed": failed,
        "skipped": skipped,
    }


def process_ready_rows(logger=None):
    logger = logger or build_logger()
    config = load_config(logger=logger)
    sources = config["sources"]

    results = []
    total_processed = 0
    total_sent = 0
    total_failed = 0
    total_skipped = 0

    for source_config in sources:
        try:
            summary = process_source_ready_rows(source_config, logger=logger)
            results.append(summary)
            total_processed += summary["processed"]
            total_sent += summary["sent"]
            total_failed += summary["failed"]
            total_skipped += summary.get("skipped", 0)
        except Exception as exc:
            logger.exception("Failed processing source [%s]", source_config["id"])
            results.append({"source_id": source_config["id"], "error": str(exc)})

    return {
        "processed": total_processed,
        "sent": total_sent,
        "failed": total_failed,
        "skipped": total_skipped,
        "sources": results,
    }


def main():
    logger = build_logger()
    logger.info("Starting one-shot zns_pull processing")
    summary = process_ready_rows(logger=logger)
    logger.info("One-shot processing summary: %s", summary)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()