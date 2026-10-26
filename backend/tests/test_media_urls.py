"""媒体链接签名（/uploads 受控访问）单元测试。"""
import time

from app.core.media_urls import (
    media_signature,
    object_name_from_url,
    sign_media_url,
    verify_media_signature,
)


def test_sign_and_verify_roundtrip():
    url = sign_media_url("/uploads/proj-1/a.png")
    assert url is not None and url.startswith("/uploads/proj-1/a.png?exp=")
    assert "&sig=" in url

    exp = int(url.split("exp=")[1].split("&")[0])
    sig = url.split("sig=")[1]
    assert verify_media_signature("proj-1/a.png", exp, sig)


def test_verify_rejects_wrong_object():
    url = sign_media_url("/uploads/proj-1/a.png")
    exp = int(url.split("exp=")[1].split("&")[0])
    sig = url.split("sig=")[1]
    assert not verify_media_signature("proj-1/b.png", exp, sig)


def test_verify_rejects_tampered_exp_and_sig():
    url = sign_media_url("/uploads/proj-1/a.png")
    exp = int(url.split("exp=")[1].split("&")[0])
    sig = url.split("sig=")[1]
    assert not verify_media_signature("proj-1/a.png", exp + 3600, sig)
    assert not verify_media_signature("proj-1/a.png", exp, sig[:-1] + ("0" if sig[-1] != "0" else "1"))


def test_verify_rejects_expired():
    exp = int(time.time()) - 1
    sig = media_signature("proj-1/a.png", exp)
    assert not verify_media_signature("proj-1/a.png", exp, sig)


def test_sign_external_url_untouched():
    assert sign_media_url("https://cdn.example.com/x.png") == "https://cdn.example.com/x.png"
    assert sign_media_url(None) is None
    assert sign_media_url("") is None


def test_object_name_from_url():
    assert object_name_from_url("/uploads/proj-1/a.png") == "proj-1/a.png"
    assert object_name_from_url("/uploads/proj-1/a.png?exp=1&sig=2") == "proj-1/a.png"
    assert object_name_from_url("/static/x.png") is None
