import io

import pytest
import redis
from markdown_web import assets
from PIL import Image


def _image_bytes(image_format: str, size: tuple[int, int] = (32, 24)) -> bytes:
    mode = "RGB" if image_format == "JPEG" else "RGBA"
    color = (20, 40, 60) if mode == "RGB" else (20, 40, 60, 128)
    image = Image.new(mode, size, color)
    output = io.BytesIO()
    image.save(output, format=image_format)
    return output.getvalue()


def test_optimized_webp_resizes_and_preserves_transparency() -> None:
    optimized = assets._optimized_webp(_image_bytes("PNG", (2400, 1200)))

    with Image.open(io.BytesIO(optimized)) as image:
        assert image.format == "WEBP"
        assert image.size == (1280, 640)
        assert image.mode == "RGBA"


def test_optimized_webp_rejects_unsupported_and_animated_images() -> None:
    with pytest.raises(assets.InvalidImageError, match="valid PNG"):
        assets._optimized_webp(b"not an image")

    animated = io.BytesIO()
    frames = [Image.new("RGB", (10, 10), color) for color in ("red", "blue")]
    frames[0].save(animated, format="WEBP", save_all=True, append_images=frames[1:])
    with pytest.raises(assets.InvalidImageError, match="Animated"):
        assets._optimized_webp(animated.getvalue())


def test_upload_image_reserves_quota_and_stores_optimized_webp(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    class FakeR2:
        def put_object(self, **kwargs: object) -> None:
            calls.update(kwargs)

    monkeypatch.setattr(
        assets,
        "_r2_settings",
        lambda: ("account", "bucket", "access", "secret", "https://media.example"),
    )
    monkeypatch.setattr(assets, "_reserve_quota", lambda client_ip, size: calls.update(client_ip=client_ip, size=size))
    monkeypatch.setattr(assets, "_r2_client", lambda *args: FakeR2())
    monkeypatch.setattr(assets.uuid, "uuid4", lambda: type("UUID", (), {"hex": "a" * 32})())

    source = _image_bytes("JPEG", (1600, 900))
    result = assets.upload_image(source, "127.0.0.1")

    assert result == "https://media.example/images/" + "a" * 32 + ".webp"
    assert calls["client_ip"] == "127.0.0.1"
    assert calls["size"] == len(source)
    assert calls["Bucket"] == "bucket"
    assert calls["Key"] == "images/" + "a" * 32 + ".webp"
    assert calls["ContentType"] == "image/webp"
    with Image.open(io.BytesIO(calls["Body"])) as image:  # type: ignore[arg-type]
        assert image.size == (1280, 720)


def test_upload_image_rejects_empty_and_oversized_data(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(assets, "_r2_settings", lambda: pytest.fail("configuration should not be reached"))

    with pytest.raises(assets.InvalidImageError, match="empty"):
        assets.upload_image(b"", "127.0.0.1")
    with pytest.raises(assets.InvalidImageError, match="20 MB"):
        assets.upload_image(b"x" * (assets.MAX_IMAGE_UPLOAD_BYTES + 1), "127.0.0.1")


def test_image_quota_distinguishes_missing_and_unreachable_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REDIS_URL", raising=False)
    with pytest.raises(assets.ImageUploadUnavailableError, match="REDIS_URL is missing"):
        assets._reserve_quota("127.0.0.1", 100)

    class UnreachableRedis:
        def eval(self, *args: object) -> None:
            raise redis.ConnectionError

    monkeypatch.setattr(assets.jobs, "_redis_client", UnreachableRedis)
    with pytest.raises(assets.ImageUploadUnavailableError, match="Redis quota check failed"):
        assets._reserve_quota("127.0.0.1", 100)
