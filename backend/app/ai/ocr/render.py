import base64
import hashlib
import io
import math
from pathlib import Path

import pypdfium2
from PIL import Image, ImageChops

POINTS_PER_INCH = 72


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def page_count(path: Path) -> int:
    document = pypdfium2.PdfDocument(str(path))
    try:
        return len(document)
    finally:
        document.close()


EDGE_THRESHOLD = 40
CUT_WINDOW_SHARE = 0.25


def render_page_image(path: Path, page_number: int, dpi: int, max_side_pixels: int) -> Image.Image:
    document = pypdfium2.PdfDocument(str(path))
    try:
        page = document[page_number - 1]
        width, height = page.get_size()
        scale = dpi / POINTS_PER_INCH
        longest = max(width, height) * scale
        if longest > max_side_pixels:
            scale *= max_side_pixels / longest
        return page.render(scale=scale).to_pil().convert("RGB")
    finally:
        document.close()


def _png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def render_page_png(path: Path, page_number: int, dpi: int, max_side_pixels: int) -> bytes:
    return _png_bytes(render_page_image(path, page_number, dpi, max_side_pixels))


def row_ink(image: Image.Image) -> list[int]:
    gray = image.convert("L")
    edges = ImageChops.difference(gray, ImageChops.offset(gray, 1, 0)).point(
        lambda value: 255 if value > EDGE_THRESHOLD else 0
    )
    return list(edges.resize((1, image.height), Image.Resampling.BOX).get_flattened_data())


def cut_positions(ink: list[int], tile_count: int) -> list[int]:
    height = len(ink)
    cuts = []
    for index in range(1, tile_count):
        target = round(height * index / tile_count)
        window = int(height / tile_count * CUT_WINDOW_SHARE)
        low, high = max(1, target - window), min(height - 1, target + window)
        cuts.append(_gap_center(ink, low, high, target))
    return cuts


def _gap_center(ink: list[int], low: int, high: int, target: int) -> int:
    quietest = min(ink[low : high + 1])
    runs: list[list[int]] = []
    for row in range(low, high + 1):
        if ink[row] != quietest:
            continue
        if runs and runs[-1][-1] == row - 1:
            runs[-1].append(row)
        else:
            runs.append([row])
    nearest = min(runs, key=lambda run: abs((run[0] + run[-1]) // 2 - target))
    return (nearest[0] + nearest[-1]) // 2


def split_into_tiles(image: Image.Image, max_tile_height: int) -> list[Image.Image]:
    tile_count = max(1, math.ceil(image.height / max_tile_height))
    if tile_count == 1:
        return [image]
    bounds = [0, *cut_positions(row_ink(image), tile_count), image.height]
    return [
        image.crop((0, top, image.width, bottom)) for top, bottom in zip(bounds, bounds[1:], strict=False)
    ]


def render_page_tiles(
    path: Path, page_number: int, dpi: int, max_side_pixels: int, max_tile_height: int
) -> list[bytes]:
    image = render_page_image(path, page_number, dpi, max_side_pixels)
    return [_png_bytes(tile) for tile in split_into_tiles(image, max_tile_height)]


def png_data_url(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")
