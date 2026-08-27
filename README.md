# ZNS Pull Deploy

## Mã nguồn

- Repo này chứa trực tiếp mã deploy Ubuntu.

Trên Ubuntu, dùng `git clone` lần đầu và `git pull` cho các lần cập nhật sau.

## Chuẩn bị cấu hình

Sau khi pull code về Ubuntu, tạo file config thật từ file mẫu:

```bash
cd /opt/zns_pull_repo
cp zns_pull_config.example.json zns_pull_config.json
nano zns_pull_config.json
```

Điền secret thật vào `zns_pull_config.json`. File config cần có các trường sau:

- `spreadsheet_id`
- `sheet_name`
- `zns_auth_key`
- `zns_from`
- `zns_template_id`
- `service_account_json`
- `poll_interval_sec`
- `request_timeout_sec`
- `max_sanphamua_length`
- `lookback_rows`
- `full_scan_interval_cycles`

## Deploy lên Ubuntu

```bash
cd /opt
sudo git clone <repo-github> zns_pull_repo
sudo chown -R $USER:$USER /opt/zns_pull_repo
cd /opt/zns_pull_repo

python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

Nếu code đã có sẵn trên máy Ubuntu và chỉ cần cập nhật:

```bash
cd /opt/zns_pull_repo
git pull
if [ ! -f zns_pull_config.json ]; then cp zns_pull_config.example.json zns_pull_config.json; fi
. .venv/bin/activate
pip install -r requirements.txt
```

## Chạy thử thủ công

```bash
cd /opt/zns_pull_repo
. .venv/bin/activate
python zns_pull_worker.py
```

Nếu chỉ muốn chạy một vòng để kiểm tra log:

```bash
cd /opt/zns_pull_repo
. .venv/bin/activate
python zns_processor.py
```

## Cài service trên Ubuntu

Sửa file `deploy/zns-pull.service` cho khớp đường dẫn thực tế nếu cần. Với ví dụ clone ở trên, nên dùng:

- `WorkingDirectory=/opt/zns_pull_repo`
- `ExecStart=/opt/zns_pull_repo/.venv/bin/python /opt/zns_pull_repo/zns_pull_worker.py`

Sau đó cài service:

```bash
cd /opt/zns_pull_repo
sudo cp deploy/zns-pull.service /etc/systemd/system/zns-pull.service
sudo systemctl daemon-reload
sudo systemctl enable zns-pull.service
sudo systemctl start zns-pull.service
sudo systemctl status zns-pull.service
```

## Cập nhật code sau này

Khi có thay đổi mới trên GitHub:

```bash
cd /opt/zns_pull_repo
git pull
. .venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart zns-pull.service
sudo systemctl status zns-pull.service
```

## Triển khai Google Apps Script

1. Mở Apps Script của Google Sheet.
2. Copy các file Apps Script từ nguồn lưu riêng của anh/chị.
3. Reload Google Sheet.
4. Bấm `Bắt đầu tự động` một lần để cài trigger.

## Kiểm tra vận hành

Xem log service:

```bash
sudo journalctl -u zns-pull.service -f
```

Kiểm tra trạng thái service:

```bash
sudo systemctl status zns-pull.service
```