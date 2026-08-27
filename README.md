# ZNS Pull Deploy

Repo này chứa phần worker Python để chạy trên Ubuntu.

## Deploy lần đầu

```bash
cd /opt
sudo git clone https://github.com/trangdc-lloyd/zns.git zns_pull_repo
sudo chown -R $USER:$USER /opt/zns_pull_repo
cd /opt/zns_pull_repo

python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

cp zns_pull_config.example.json zns_pull_config.json
nano zns_pull_config.json
```

Sau khi mở `nano`, điền config thật vào `zns_pull_config.json`, lưu bằng `Ctrl + O`, Enter, rồi thoát bằng `Ctrl + X`.

## Chạy thử thủ công

Chạy worker nền bằng tay:

```bash
cd /opt/zns_pull_repo
. .venv/bin/activate
python zns_pull_worker.py
```

Chỉ chạy một vòng để kiểm tra log:

```bash
cd /opt/zns_pull_repo
. .venv/bin/activate
python zns_processor.py
```

## Cài service production

File service mẫu đã dùng đường dẫn này:

- `WorkingDirectory=/opt/zns_pull_repo`
- `ExecStart=/opt/zns_pull_repo/.venv/bin/python /opt/zns_pull_repo/zns_pull_worker.py`

Cài service:

```bash
cd /opt/zns_pull_repo
sudo cp deploy/zns-pull.service /etc/systemd/system/zns-pull.service
sudo systemctl daemon-reload
sudo systemctl enable zns-pull.service
sudo systemctl start zns-pull.service
sudo systemctl status zns-pull.service
```

Xem log runtime:

```bash
sudo journalctl -u zns-pull.service -f
```

## Cập nhật code

```bash
cd /opt/zns_pull_repo
git pull
if [ ! -f zns_pull_config.json ]; then cp zns_pull_config.example.json zns_pull_config.json; fi
. .venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart zns-pull.service
sudo systemctl status zns-pull.service
```

## Apps Script

1. Mở Apps Script của Google Sheet.
2. Copy các file Apps Script từ nguồn lưu riêng của anh/chị.
3. Reload Google Sheet.
4. Bấm `Bắt đầu tự động` một lần để cài trigger.