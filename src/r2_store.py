# src/r2_store.py
# 숏폼 팩토리 — Cloudflare R2 보관소 (S3 호환 API)
#
# 왜 필요한가:
#   - 1시간 음악 영상(약 600MB)은 Streamlit 화면에서 바로 내려받게 하면 서버 메모리를 크게 쓴다.
#     → 서버는 R2 에 올리고, 사용자는 7일짜리 서명 링크로 R2 에서 직접 받는다.
#   - 서버가 재시작돼도 R2 에 올린 이미지·클립·음악은 남는다.
#
# Streamlit Secrets:
#   R2_ENDPOINT, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET
#
# 공식 문서 기준: 서명 링크는 1초~7일(604,800초), boto3 로 생성.

import time
from urllib.parse import urlparse

LINK_MAX_SECONDS = 604_800          # 7일
REQUIRED = ("R2_ENDPOINT", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET")


def missing_keys(keys: dict) -> list:
    return [k for k in REQUIRED if not str(keys.get(k, "")).strip()]


def is_configured(keys: dict) -> bool:
    return not missing_keys(keys)


def _clean_endpoint(endpoint: str) -> str:
    """버킷 경로까지 붙여 넣은 경우에도 https://<계정>.r2.cloudflarestorage.com 만 남긴다."""
    endpoint = endpoint.strip().rstrip("/")
    if not endpoint.startswith("http"):
        endpoint = "https://" + endpoint
    u = urlparse(endpoint)
    return f"{u.scheme}://{u.netloc}"


def _client(keys: dict):
    import boto3
    from botocore.config import Config
    return boto3.client(
        "s3",
        endpoint_url=_clean_endpoint(keys["R2_ENDPOINT"]),
        aws_access_key_id=keys["R2_ACCESS_KEY_ID"].strip(),
        aws_secret_access_key=keys["R2_SECRET_ACCESS_KEY"].strip(),
        region_name="auto",
        config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
    )


def upload_file(keys: dict, local_path: str, key: str, content_type: str = "") -> str:
    """디스크의 파일을 조각 단위로 올린다(큰 파일도 메모리에 통째로 올리지 않음). 올린 key 를 돌려준다."""
    extra = {"ContentType": content_type} if content_type else None
    _client(keys).upload_file(local_path, keys["R2_BUCKET"].strip(), key, ExtraArgs=extra)
    return key


def download_link(keys: dict, key: str, seconds: int = LINK_MAX_SECONDS, filename: str = "") -> str:
    params = {"Bucket": keys["R2_BUCKET"].strip(), "Key": key}
    if filename:
        params["ResponseContentDisposition"] = f'attachment; filename="{filename}"'
    return _client(keys).generate_presigned_url(
        "get_object", Params=params, ExpiresIn=min(int(seconds), LINK_MAX_SECONDS))


def test_connection(keys: dict) -> dict:
    """작은 글 파일을 올리고 → 정보 조회 → 서명 링크로 다시 받아 내용이 같은지 확인한다."""
    import requests
    report = {"ok": False, "steps": [], "link": ""}
    miss = missing_keys(keys)
    if miss:
        report["steps"].append(("Secrets 확인", False, "없는 값: " + ", ".join(miss)))
        return report
    report["steps"].append(("Secrets 확인", True, f"버킷 {keys['R2_BUCKET'].strip()} · "
                                                  f"주소 {_clean_endpoint(keys['R2_ENDPOINT'])}"))
    key = "_tests/connection_test.txt"
    body = f"makingshorts-engine R2 test {time.strftime('%Y-%m-%d %H:%M:%S')}".encode()
    try:
        c = _client(keys)
        c.put_object(Bucket=keys["R2_BUCKET"].strip(), Key=key, Body=body, ContentType="text/plain")
        report["steps"].append(("파일 올리기", True, key))
        h = c.head_object(Bucket=keys["R2_BUCKET"].strip(), Key=key)
        report["steps"].append(("파일 확인", True, f"{h.get('ContentLength')} bytes"))
        link = download_link(keys, key, seconds=600)
        r = requests.get(link, timeout=30)
        same = r.status_code == 200 and r.content == body
        report["steps"].append(("서명 링크로 받기", same, f"HTTP {r.status_code}"))
        report["link"] = link
        report["ok"] = same
    except Exception as e:
        report["steps"].append(("오류", False, f"{type(e).__name__}: {e}"))
    return report
