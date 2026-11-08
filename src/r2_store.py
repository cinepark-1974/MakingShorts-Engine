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


def download_file(keys: dict, key: str, local_path: str) -> str:
    """R2 의 파일을 디스크로 받는다 (서버 재시작·JSON 복구 뒤 재료 되살리기)."""
    import os
    os.makedirs(os.path.dirname(local_path) or ".", exist_ok=True)
    _client(keys).download_file(keys["R2_BUCKET"].strip(), key, local_path)
    return local_path


def get_json(keys: dict, key: str):
    """R2 의 작은 JSON 파일을 읽는다. 없으면 None."""
    import json
    try:
        obj = _client(keys).get_object(Bucket=keys["R2_BUCKET"].strip(), Key=key)
        return json.loads(obj["Body"].read().decode("utf-8"))
    except Exception as e:
        if "NoSuchKey" in str(e) or "404" in str(e):
            return None
        raise


def put_json(keys: dict, key: str, data) -> None:
    import json
    _client(keys).put_object(Bucket=keys["R2_BUCKET"].strip(), Key=key,
                             Body=json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8"),
                             ContentType="application/json")


def list_prefix(keys: dict, prefix: str) -> list:
    """prefix 아래 파일 목록 [{key, size, at}] (최근 것부터)."""
    c = _client(keys)
    bucket = keys["R2_BUCKET"].strip()
    out, token = [], None
    while True:
        kw = {"Bucket": bucket, "Prefix": prefix}
        if token:
            kw["ContinuationToken"] = token
        res = c.list_objects_v2(**kw)
        for o in res.get("Contents", []):
            at = o.get("LastModified")
            out.append({"key": o["Key"], "size": int(o.get("Size") or 0),
                        "at": at.strftime("%m-%d %H:%M") if hasattr(at, "strftime") else str(at or "")})
        if not res.get("IsTruncated"):
            break
        token = res.get("NextContinuationToken")
    return sorted(out, key=lambda x: x["at"], reverse=True)


def delete_prefix(keys: dict, prefix: str, keep: tuple = ()) -> int:
    """prefix 아래 파일을 모두 지운다 (keep 에 든 파일 이름은 남김). 지운 개수를 돌려준다."""
    c = _client(keys)
    bucket = keys["R2_BUCKET"].strip()
    n, token = 0, None
    while True:
        kw = {"Bucket": bucket, "Prefix": prefix}
        if token:
            kw["ContinuationToken"] = token
        res = c.list_objects_v2(**kw)
        objs = [{"Key": o["Key"]} for o in res.get("Contents", []) if o["Key"].rsplit("/", 1)[-1] not in keep]
        for i in range(0, len(objs), 1000):
            c.delete_objects(Bucket=bucket, Delete={"Objects": objs[i:i + 1000], "Quiet": True})
            n += len(objs[i:i + 1000])
        if not res.get("IsTruncated"):
            return n
        token = res.get("NextContinuationToken")


def download_link(keys: dict, key: str, seconds: int = LINK_MAX_SECONDS, filename: str = "") -> str:
    params = {"Bucket": keys["R2_BUCKET"].strip(), "Key": key}
    if filename:
        from src.naming import content_disposition
        params["ResponseContentDisposition"] = content_disposition(filename)
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
