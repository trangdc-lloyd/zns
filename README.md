# ZNS Pull Deploy

Repo này chứa phần worker Python để chạy trên Ubuntu.

## Deploy Docker

Nếu máy Ubuntu chưa có Docker:

```bash
sudo apt update
sudo apt install docker.io docker-compose-plugin -y
sudo systemctl enable docker
sudo systemctl start docker
```

## Chạy lần đầu

```bash
cd /opt
sudo git clone https://github.com/trangdc-lloyd/zns.git zns_pull_repo
sudo chown -R $USER:$USER /opt/zns_pull_repo
cd /opt/zns_pull_repo

cp zns_pull_config.example.json zns_pull_config.json
nano zns_pull_config.json
touch zns_pull_state.json

docker compose up -d --build
docker compose logs -f
```

Sau khi mở `nano`, điền config thật vào `zns_pull_config.json`, lưu bằng `Ctrl + O`, Enter, rồi thoát bằng `Ctrl + X`.

Các file Docker đang dùng:

- `Dockerfile`: image cho worker Python
- `docker-compose.yml`: chạy container nền và mount file config thật
- `.dockerignore`: không đưa secret và file runtime vào image build

## Kiểm tra container

```bash
cd /opt/zns_pull_repo
docker compose ps
docker compose logs -f
```

## Cập nhật code

```bash
cd /opt/zns_pull_repo
git pull
if [ ! -f zns_pull_config.json ]; then cp zns_pull_config.example.json zns_pull_config.json; fi
if [ ! -f zns_pull_state.json ]; then touch zns_pull_state.json; fi
docker compose up -d --build
docker compose logs -f
```

## Điều khiển container

```bash
cd /opt/zns_pull_repo
docker compose ps
docker compose stop
docker compose start
docker compose restart
docker compose logs -f
```

## Apps Script

1. Mở Apps Script của Google Sheet.
2. Copy các file Apps Script từ nguồn lưu riêng của anh/chị.
3. Reload Google Sheet.
4. Bấm `Bắt đầu tự động` một lần để cài trigger.