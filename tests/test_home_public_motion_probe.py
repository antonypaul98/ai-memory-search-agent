"""No-network fixture provenance and download safety tests."""
from hashlib import sha256
import stat
import pytest

from scripts.home_public_motion_probe import (download_public_fixture, create_public_frame_montage,
                                              SOURCE_URL, BOTTLE_SOURCE_URL, BOTTLE_SOURCE_PAGE, MAX_BYTES)


class FakeResponse:
    def __init__(self, data=b"x" * 1200, url=SOURCE_URL, media="video/webm"):
        self.data = data
        self.url = url
        self.headers = {"Content-Type": media}
    def __enter__(self):
        return self
    def __exit__(self, *_):
        return False
    def geturl(self):
        return self.url
    def read(self, limit):
        return self.data[:limit]


def test_private_fixture_provenance_and_no_overwrite(tmp_path):
    path = tmp_path / "clip.webm"
    data = b"v" * 1200
    result = download_public_fixture(path, opener=lambda request, timeout: FakeResponse(data=data))
    assert path.read_bytes() == data
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert result["sha256"] == sha256(data).hexdigest()
    assert result["author"] == "Pittigrilli"
    with pytest.raises(ValueError):
        download_public_fixture(path, opener=lambda *_a, **_k: FakeResponse())


@pytest.mark.parametrize("response", [
    FakeResponse(url="https://example.org/malicious.webm"),
    FakeResponse(media="text/html"),
    FakeResponse(data=b"short"),
    FakeResponse(data=b"x" * (MAX_BYTES + 1)),
])
def test_untrusted_or_malformed_fixture_rejected(tmp_path, response):
    path = tmp_path / "clip.webm"
    with pytest.raises(ValueError):
        download_public_fixture(path, opener=lambda request, timeout: response)
    assert not path.exists()



def test_public_fixture_review_montage_is_bounded_and_private(tmp_path):
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    from PIL import Image
    video = tmp_path / "public-test.avi"
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"MJPG"), 5, (320, 180))
    if not writer.isOpened():
        pytest.skip("MJPG codec unavailable")
    try:
        for i in range(32):
            frame = np.zeros((180, 320, 3), dtype=np.uint8)
            cv2.rectangle(frame, (10 + i, 50), (60 + i, 110), (255, 255, 255), -1)
            writer.write(frame)
    finally:
        writer.release()
    destination = tmp_path / "review.jpg"
    result = create_public_frame_montage(video, destination)
    assert result == {"sampled_frames": [0, 30], "width": 960,
                      "height": 368, "public_fixture_only": True}
    assert Image.open(destination).size == (960, 368)
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    with pytest.raises(ValueError):
        create_public_frame_montage(video, destination)


def test_bottle_fixture_is_explicit_and_provenance_is_correct(tmp_path):
    path = tmp_path / "bottle.webm"
    payload = b"v" * 1200
    result = download_public_fixture(
        path, fixture="bottle",
        opener=lambda request, timeout: FakeResponse(data=payload, url=BOTTLE_SOURCE_URL))
    assert result["author"] == "Cirosantilli2"
    assert result["source"] == BOTTLE_SOURCE_PAGE
    assert result["sha256"] == sha256(payload).hexdigest()


def test_unknown_fixture_rejected_without_download(tmp_path):
    path = tmp_path / "fixture.webm"
    with pytest.raises(ValueError, match="unsupported"):
        download_public_fixture(path, fixture="untrusted",
                                opener=lambda *_a, **_k: pytest.fail("network called"))
    assert not path.exists()
