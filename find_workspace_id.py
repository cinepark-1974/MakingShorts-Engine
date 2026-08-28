# find_workspace_id.py
# 이 스크립트를 한 번만 실행하면 워크스페이스 ID를 확인할 수 있습니다.
# 실행: python find_workspace_id.py

import requests
import sys

API_KEY = input("ANTHROPIC_API_KEY를 입력하세요: ").strip()

resp = requests.get(
    "https://api.anthropic.com/v1/workspaces",
    headers={
        "x-api-key": API_KEY,
        "anthropic-version": "2023-06-01",
    },
    timeout=10,
)

if resp.status_code == 200:
    data = resp.json()
    workspaces = data.get("data", [])
    if workspaces:
        print("\n[ 워크스페이스 목록 ]")
        for ws in workspaces:
            print(f"  이름: {ws.get('name')}")
            print(f"  ID  : {ws.get('id')}")
            print()
    else:
        print("워크스페이스가 없습니다.")
else:
    print(f"오류 ({resp.status_code}): {resp.text}")
