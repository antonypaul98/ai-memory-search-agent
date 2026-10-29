"""No-network fixture provenance and download safety tests."""
from hashlib import sha256
import stat
import pytest

from scripts.home_public_motion_probe import download_public_fixture, SOURCE_URL


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
    FakeResponse(data=b"x" * 2_000_001),
])
def test_untrusted_or_malformed_fixture_rejected(tmp_path, response):
    path = tmp_path / "clip.webm"
    with pytest.raises(ValueError):
        download_public_fixture(path, opener=lambda request, timeout: response)
    assert not path.exists()
