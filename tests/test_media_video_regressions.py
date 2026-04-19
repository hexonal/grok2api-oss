import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.grok.services.media import VideoService


def test_video_payload_includes_multi_reference_fields():
    service = VideoService()

    payload = service._build_payload(
        prompt="make it cinematic",
        post_id="post-123",
        aspect_ratio="16:9",
        video_length=10,
        resolution_name="720p",
        preset="normal",
        image_references=[
            "https://assets.grok.com/ref-1",
            "https://assets.grok.com/ref-2",
        ],
    )

    video_config = payload["responseMetadata"]["modelConfigOverride"]["modelMap"][
        "videoGenModelConfig"
    ]
    assert video_config["parentPostId"] == "post-123"
    assert video_config["imageReferences"] == [
        "https://assets.grok.com/ref-1",
        "https://assets.grok.com/ref-2",
    ]
    assert video_config["isReferenceToVideo"] is True


def test_check_limit_prunes_oldest_image_when_image_limit_exceeded(
    tmp_path, monkeypatch
):
    async def _run():
        image_dir = tmp_path / "image"
        video_dir = tmp_path / "video"
        image_dir.mkdir()
        video_dir.mkdir()

        old_image = image_dir / "old.png"
        old_image.write_bytes(b"a" * 80)
        new_image = image_dir / "new.png"
        new_image.write_bytes(b"b" * 80)
        video_file = video_dir / "keep.mp4"
        video_file.write_bytes(b"c" * 80)

        old_image.touch()
        new_image.touch()
        video_file.touch()

        download_service = __import__(
            "app.services.grok.services.assets", fromlist=["DownloadService"]
        ).DownloadService()
        download_service.image_dir = image_dir
        download_service.video_dir = video_dir

        values = {
            "cache.enable_auto_clean": True,
            "cache.limit_mb": 999,
            "cache.media_max_mb": 0,
            "cache.image_max_mb": 100 / (1024 * 1024),
            "cache.video_max_mb": 0,
        }

        def fake_get_config(key, default=None):
            return values.get(key, default)

        @asynccontextmanager
        async def fake_lock(_name: str, timeout: int = 5):
            yield

        monkeypatch.setattr(
            "app.services.grok.services.assets.get_config", fake_get_config
        )
        monkeypatch.setattr(
            "app.services.grok.services.assets._file_lock", fake_lock
        )

        await download_service.check_limit()

        assert not old_image.exists()
        assert new_image.exists()
        assert video_file.exists()

    asyncio.run(_run())
