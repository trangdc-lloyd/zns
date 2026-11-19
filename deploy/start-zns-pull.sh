#!/bin/sh
set -eu

cd /opt/zns_pull_repo
docker compose start zns-pull
