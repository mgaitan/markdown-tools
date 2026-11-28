"""Image validation, optimization, quota checks, and R2 storage."""

from __future__ import annotations

import io
import os
import uuid
from datetime import UTC, datetime
from urllib.parse import urlparse

import boto3
import redis
from botocore.exceptions import BotoCoreError, ClientError
from PIL import Image, ImageOps
from PIL.Image import UnidentifiedImageError

from markdown_web import jobs

MAX_IMAGE_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_IMAGE_DAILY_BYTES = 50 * 1024 * 1024
MAX_IMAGE_UPLOADS_PER_IP_HOUR = 10
MAX_IMAGE_DIMENSION = 1280
MAX_IMAGE_PIXELS = 25_000_000
IMAGE_UPLOAD_KEY_PREFIX = "markdown-web:image-upload"
IMAGE_OUTPUT_CONTENT_TYPE = "image/webp"
QUOTA_SCRIPT = """
local daily = redis.call('incrby', KEYS[1], ARGV[1])
local hourly = redis.call('incrby', KEYS[2], 1)
if daily == tonumber(ARGV[1]) then redis.call('expire', KEYS[1], ARGV[3]) end
if hourly == 1 then redis.call('expire', KEYS[2], ARGV[4]) end
if daily > tonumber(ARGV[2]) or hourly > tonumber(ARGV[5]) then
  redis.call('decrby', KEYS[1], ARGV[1])
  redis.call('decrby', KEYS[2], 1)
  return 0
end
return 1
"""


class ImageUploadError(ValueError):
    """Raised when an image upload cannot be accepted."""


class ImageUploadUnavailableError(ImageUploadError):
    """Raised when image upload configuration or the quota backend is unavailable."""

    def __init__(self, *, reason: str) -> None:
        super().__init__(f"Image uploads are unavailable: {reason}")


class ImageQuotaExceededError(ImageUploadError):
    """Raised when an image upload exceeds an abuse-prevention quota."""

    def __init__(self) -> None:
        super().__init__("Image upload quota exceeded; try again later")


class InvalidImageError(ImageUploadError):
    """Raised when the bytes are not a supported safe image."""


class UnsupportedImageFormatError(InvalidImageError):
    def __init__(self) -> None:
        super().__init__("Only PNG, JPEG, and WebP images are supported")


class ImageDimensionsError(InvalidImageError):
    def __init__(self) -> None:
        super().__init__("Image dimensions are too large")


class AnimatedImageError(InvalidImageError):
    def __init__(self) -> None:
        super().__init__("Animated images are not supported")


class InvalidImageDataError(InvalidImageError):
    def __init__(self) -> None:
        super().__init__("Could not read a valid PNG, JPEG, or WebP image")


class EmptyImageError(InvalidImageError):
    def __init__(self) -> None:
        super().__init__("Image is empty")


class ImageTooLargeError(InvalidImageError):
    def __init__(self) -> None:
        super().__init__("Images must be 20 MB or smaller")


class ImageStorageError(RuntimeError):
    """Raised when R2 rejects an accepted image."""

    def __init__(self) -> None:
        super().__init__("Could not store image")


def _r2_settings() -> tuple[str, str, str, str, str]:
    account_id = os.getenv("R2_ACCOUNT_ID", "")
    bucket_name = os.getenv("R2_BUCKET_NAME", "")
    access_key_id = os.getenv("R2_ACCESS_KEY_ID", "")
    secret_access_key = os.getenv("R2_SECRET_ACCESS_KEY", "")
    public_base_url = os.getenv("R2_PUBLIC_BASE_URL", "").rstrip("/")
    parsed_url = urlparse(public_base_url)
    if (
        not all((account_id, bucket_name, access_key_id, secret_access_key))
        or parsed_url.scheme not in {"http", "https"}
        or not parsed_url.netloc
    ):
        raise ImageUploadUnavailableError(reason="check the R2 configuration")
    return account_id, bucket_name, access_key_id, secret_access_key, public_base_url


def _r2_client(account_id: str, access_key_id: str, secret_access_key: str) -> object:
    return boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        region_name="auto",
    )


def _quota_keys(client_ip: str) -> tuple[str, str, int, int]:
    now = datetime.now(UTC)
    daily_key = f"{IMAGE_UPLOAD_KEY_PREFIX}:daily:{now:%Y-%m-%d}"
    hourly_key = f"{IMAGE_UPLOAD_KEY_PREFIX}:ip:{client_ip}:{now:%Y-%m-%d-%H}"
    seconds_until_day_end = 24 * 60 * 60 - (now.hour * 60 * 60 + now.minute * 60 + now.second)
    seconds_until_hour_end = 60 * 60 - (now.minute * 60 + now.second)
    return daily_key, hourly_key, seconds_until_day_end, seconds_until_hour_end


def _reserve_quota(client_ip: str, size: int) -> None:
    try:
        client = jobs._redis_client()
    except jobs.JobsUnavailableError as exc:
        raise ImageUploadUnavailableError(reason="REDIS_URL is missing") from exc
    except ValueError as exc:
        raise ImageUploadUnavailableError(reason="REDIS_URL is invalid") from exc
    daily_key, hourly_key, daily_ttl, hourly_ttl = _quota_keys(client_ip)
    try:
        reserved = client.eval(
            QUOTA_SCRIPT,
            2,
            daily_key,
            hourly_key,
            str(size),
            str(MAX_IMAGE_DAILY_BYTES),
            str(daily_ttl),
            str(hourly_ttl),
            str(MAX_IMAGE_UPLOADS_PER_IP_HOUR),
        )
    except redis.RedisError as exc:
        raise ImageUploadUnavailableError(reason="the Redis quota check failed") from exc
    if int(reserved or 0) != 1:
        raise ImageQuotaExceededError


def _optimized_webp(data: bytes) -> bytes:
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in {"PNG", "JPEG", "WEBP"}:
                raise UnsupportedImageFormatError
            input_format = image.format
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise ImageDimensionsError
            if getattr(image, "is_animated", False):
                raise AnimatedImageError
            has_alpha = "A" in image.getbands() or "transparency" in image.info
            transposed = ImageOps.exif_transpose(image)
            transposed.thumbnail((MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION), Image.Resampling.LANCZOS)
            converted = transposed.convert("RGBA" if has_alpha else "RGB")
            output = io.BytesIO()
            save_options: dict[str, object] = {"format": "WEBP", "method": 6}
            if input_format == "PNG":
                save_options["lossless"] = True
            else:
                save_options["quality"] = 85
            converted.save(output, **save_options)
            return output.getvalue()
    except InvalidImageError:
        raise
    except (Image.DecompressionBombError, OSError, UnidentifiedImageError) as exc:
        raise InvalidImageDataError from exc


def upload_image(data: bytes, client_ip: str) -> str:
    """Validate, optimize, quota-check, and upload one image to R2."""
    if not data:
        raise EmptyImageError
    if len(data) > MAX_IMAGE_UPLOAD_BYTES:
        raise ImageTooLargeError
    account_id, bucket_name, access_key_id, secret_access_key, public_base_url = _r2_settings()
    _reserve_quota(client_ip or "unknown", len(data))
    optimized = _optimized_webp(data)
    key = f"images/{uuid.uuid4().hex}.webp"
    client = _r2_client(account_id, access_key_id, secret_access_key)
    try:
        client.put_object(
            Bucket=bucket_name,
            Key=key,
            Body=optimized,
            ContentType=IMAGE_OUTPUT_CONTENT_TYPE,
            CacheControl="public, max-age=31536000, immutable",
        )
    except (BotoCoreError, ClientError) as exc:
        raise ImageStorageError from exc
    return f"{public_base_url}/{key}"
