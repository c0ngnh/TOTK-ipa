#!/usr/bin/env python3
"""PNG reading, writing and scaling, with the standard library only.

The app's home screen icon must be the same bytes on every machine that builds it: the kit's own icon is checked by
its sha256 (tools/app_icon.py), so the files written into the app cannot depend on which encoder produced them. A
machine that has ImageMagick and one that has not would otherwise write different bytes for the same image, and the
check would fail on one of them.

So nothing here calls out to an image tool. On Windows there is none to call: ImageMagick is not installed, ffmpeg is
not installed, and `convert` is not ImageMagick either but the system's own FAT-to-NTFS converter, which prints
"Invalid Parameter - -resize" and exits. That is what stopped the Windows build with "no image tool for the icon".

    png_image.py <source.png> <size> <output.png>     # scale an icon
"""
import struct
import sys
import zlib
from itertools import accumulate
from pathlib import Path

PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'


def _chunks(data):
    """A PNG file's chunks, as (tag, data) pairs."""
    if not data.startswith(PNG_SIGNATURE):
        raise SystemExit('not a PNG file')
    at = len(PNG_SIGNATURE)
    while at + 8 <= len(data):
        length = struct.unpack('>I', data[at:at + 4])[0]
        tag = data[at + 4:at + 8]
        yield tag, data[at + 8:at + 8 + length]
        at += 12 + length


def _unfilter(raw, width, height, channels):
    """The decompressed scanlines back to plain RGB bytes.

    A PNG row is stored as the difference from the row above, or from the pixel to the left, or both; the filter type
    says which. The five filter types are undone here, because the icon the kit ships uses them all.
    """
    stride = width * channels
    out = bytearray()
    prev = bytearray(stride)
    at = 0
    for _ in range(height):
        kind = raw[at]
        at += 1
        line = bytearray(raw[at:at + stride])
        at += stride
        if kind == 1:      # Sub: the difference from the pixel to the left
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 0xff
        elif kind == 2:    # Up: the difference from the row above
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xff
        elif kind == 3:    # Average: the mean of the two neighbours
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xff
        elif kind == 4:    # Paeth: the best of the three neighbours
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                up = prev[i]
                upleft = prev[i - channels] if i >= channels else 0
                p = left + up - upleft
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - upleft)
                if pa <= pb and pa <= pc:
                    near = left
                elif pb <= pc:
                    near = up
                else:
                    near = upleft
                line[i] = (line[i] + near) & 0xff
        elif kind != 0:    # None: the row is stored as it is
            raise SystemExit(f'the PNG uses the unknown filter type {kind}')
        out += line
        prev = line
    return bytes(out)


def read_png(path):
    """A PNG file to (width, height, RGB bytes).

    Only what an icon is: 8 bits per channel, not interlaced. The colour types of a grey, grey+alpha, RGB and RGBA
    image are all read, and the result always has three channels, so the caller does not have to care which one it was.
    """
    data = Path(path).read_bytes()
    width = height = depth = colour = interlace = None
    idat = bytearray()
    for tag, body in _chunks(data):
        if tag == b'IHDR':
            width, height, depth, colour, _compression, _filter, interlace = struct.unpack('>IIBBBBB', body)
        elif tag == b'IDAT':
            idat += body
        elif tag == b'IEND':
            break
    if width is None:
        raise SystemExit(f'{path} is not a PNG file')
    if depth != 8:
        raise SystemExit(f'{path} is a {depth}-bit PNG; the icon must be 8 bits per channel')
    if interlace:
        raise SystemExit(f'{path} is interlaced; the icon must not be')
    channels = {0: 1, 2: 3, 4: 2, 6: 4}.get(colour)
    if channels is None:
        raise SystemExit(f'{path} is a PNG of the colour type {colour}; the icon must be grey or RGB')
    pixels = _unfilter(zlib.decompress(bytes(idat)), width, height, channels)
    if channels == 3:
        return width, height, pixels
    rgb = bytearray(width * height * 3)
    for i in range(width * height):
        if channels == 1:
            grey = pixels[i]
            rgb[i * 3:i * 3 + 3] = bytes((grey, grey, grey))
        elif channels == 2:
            grey = pixels[i * 2]
            rgb[i * 3:i * 3 + 3] = bytes((grey, grey, grey))
        else:
            rgb[i * 3:i * 3 + 3] = pixels[i * 4:i * 4 + 3]
    return width, height, bytes(rgb)


def write_png(path, width, height, rgb):
    """RGB bytes to a PNG file (8-bit truecolour, no alpha).

    The bytes depend on nothing but the pixels: the same image always gives the same file, on every machine.
    """
    raw = bytearray()
    for y in range(height):
        raw.append(0)   # filter type 0 (none)
        raw += rgb[y * width * 3:(y + 1) * width * 3]

    def chunk(tag, body):
        return struct.pack('>I', len(body)) + tag + body + struct.pack('>I', zlib.crc32(tag + body) & 0xffffffff)

    png = PNG_SIGNATURE
    png += chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
    png += chunk(b'IDAT', zlib.compress(bytes(raw), 9))
    png += chunk(b'IEND', b'')
    Path(path).write_bytes(png)


def _spans(size, count):
    """The source range each target index reads, as (first, last) pairs."""
    spans = []
    for i in range(count):
        first = i * size // count
        last = max(((i + 1) * size + count - 1) // count, first + 1)
        spans.append((first, min(last, size)))
    return spans


def resize(width, height, rgb, new_width, new_height):
    """An RGB image to another size, by averaging the pixels of each area.

    The icon is a small image shown at a small size, so a plain area average is what it wants: every target pixel is
    the mean of the source pixels it covers. The result depends on nothing but the bytes of the source, so it is the
    same on every machine.
    """
    if (width, height) == (new_width, new_height):
        return rgb
    x_spans = _spans(width, new_width)
    y_spans = _spans(height, new_height)

    # Each source row, one sum per target column and channel: the mean is not taken yet, only the sum.
    row_sums = []
    for y in range(height):
        line = rgb[y * width * 3:(y + 1) * width * 3]
        totals = []
        for channel in range(3):
            column = line[channel::3]
            running = list(accumulate(column, initial=0))
            totals.append([running[last] - running[first] for first, last in x_spans])
        row_sums.append(totals)

    # Then each target row: the sum of the source rows it covers, divided by the number of pixels it covers.
    out = bytearray()
    for first, last in y_spans:
        rows = last - first
        for x in range(new_width):
            count = rows * (x_spans[x][1] - x_spans[x][0])
            for channel in range(3):
                total = sum(row_sums[y][channel][x] for y in range(first, last))
                out.append(total // count)
    return bytes(out)


def main():
    if len(sys.argv) != 4:
        print(__doc__)
        return 2
    source, size, target = Path(sys.argv[1]), int(sys.argv[2]), Path(sys.argv[3])
    width, height, rgb = read_png(source)
    write_png(target, size, size, resize(width, height, rgb, size, size))
    print(f'{source}: {width}x{height} -> {target}: {size}x{size}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
