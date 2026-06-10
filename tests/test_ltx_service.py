"""Unit tests for the LTX service helpers (no network)."""

from PIL import Image

from backend.services import ltx_service


def _make_image(tmp_path, width, height):
    path = tmp_path / f"img_{width}x{height}.jpg"
    Image.new("RGB", (width, height), (200, 180, 160)).save(path, "JPEG")
    return path


def test_portrait_image_selects_portrait_resolution(tmp_path):
    path = _make_image(tmp_path, 800, 1200)
    uri, resolution = ltx_service._image_data_uri(path)
    assert resolution == ltx_service.PORTRAIT_RESOLUTION
    assert uri.startswith("data:image/jpeg;base64,")


def test_landscape_image_selects_landscape_resolution(tmp_path):
    path = _make_image(tmp_path, 1200, 800)
    _, resolution = ltx_service._image_data_uri(path)
    assert resolution == ltx_service.LANDSCAPE_RESOLUTION


def test_square_image_defaults_to_landscape(tmp_path):
    path = _make_image(tmp_path, 900, 900)
    _, resolution = ltx_service._image_data_uri(path)
    assert resolution == ltx_service.LANDSCAPE_RESOLUTION


def test_data_uri_stays_under_api_limit_for_large_images(tmp_path):
    # The LTX API caps base64 data URIs at 7 MB encoded.
    path = _make_image(tmp_path, 4000, 3000)
    uri, _ = ltx_service._image_data_uri(path)
    assert len(uri) < 7 * 1024 * 1024


def test_missing_api_key_raises_clean_error(tmp_path, monkeypatch):
    import dataclasses

    from backend import config

    monkeypatch.setattr(
        ltx_service, "settings", dataclasses.replace(config.settings, ltx_api_key="")
    )
    path = _make_image(tmp_path, 640, 480)
    try:
        ltx_service.generate_tryon_video(path, "subtle motion", tmp_path / "out.mp4")
        raise AssertionError("expected LTXError")
    except ltx_service.LTXError as exc:
        assert "LTX_API_KEY" in str(exc)
