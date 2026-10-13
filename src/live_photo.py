"""Windows-compatible Apple Live Photo pair writer.

QuickTime timed metadata layout follows Apple's mebx/keyd/dtyp specification.
Only album Live Photos are targeted; lock-screen wallpaper eligibility is not.
"""
import json
import math
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import uuid

import imageio_ffmpeg
import piexif
from PIL import Image
from pillow_heif import register_heif_opener

register_heif_opener(thumbnails=False)


class ConversionError(RuntimeError):
    pass


CONTENT_KEY = b'com.apple.quicktime.content.identifier'
STILL_KEY = b'com.apple.quicktime.still-image-time'
APPLE_HEADER = b'Apple iOS\0\0\x01MM'
MARKER = struct.pack('>IIb', 9, 1, 0)
TIMESCALE = 600
FRAME_TICKS = 20  # Normalized output is 30 fps.


def _box(kind, payload):
    return struct.pack('>I4s', len(payload) + 8, kind) + payload


def _full(kind, payload, flags=0):
    return _box(kind, struct.pack('>I', flags) + payload)


def _boxes(data):
    pos = 0
    while pos < len(data):
        if len(data) - pos < 8:
            raise ConversionError('MOV atom header is truncated')
        size, kind = struct.unpack_from('>I4s', data, pos)
        header = 8
        if size == 1:
            if len(data) - pos < 16:
                raise ConversionError('MOV extended atom header is truncated')
            size = struct.unpack_from('>Q', data, pos + 8)[0]
            header = 16
        if size == 0:
            size = len(data) - pos
        if size < header or pos + size > len(data):
            raise ConversionError('Invalid MOV atom size')
        yield kind, data[pos + header:pos + size], pos, size
        pos += size


def _child(data, kind):
    for tag, payload, _, _ in _boxes(data):
        if tag == kind:
            return payload
    raise ConversionError(f'Missing MOV atom: {kind!r}')


def _path(data, *kinds):
    for kind in kinds:
        data = _child(data, kind)
    return data


def _movie_timing(moov):
    header = _child(moov, b'mvhd')
    if header[0] == 0:
        scale, duration = struct.unpack_from('>II', header, 12)
    elif header[0] == 1:
        scale, duration = struct.unpack_from('>IQ', header, 20)
    else:
        raise ConversionError('Unsupported movie header version')
    if not scale or not duration:
        raise ConversionError('Video has no duration')
    return scale, duration


def _metadata_track(track_id, scale, still_ticks, chunk_offset):
    # One signed int8 sample at the exact presentation time of the cover.
    key = _box(struct.pack('>I', 1),
               _box(b'keyd', b'mdta' + STILL_KEY) +
               _box(b'dtyp', struct.pack('>II', 0, 65)))
    entry = _box(b'mebx', b'\0' * 6 + struct.pack('>H', 1) + _box(b'keys', key))
    stbl = _box(b'stbl',
                _full(b'stsd', struct.pack('>I', 1) + entry) +
                _full(b'stts', struct.pack('>III', 1, 1, FRAME_TICKS)) +
                _full(b'stsc', struct.pack('>IIII', 1, 1, 1, 1)) +
                _full(b'stsz', struct.pack('>II', len(MARKER), 1)) +
                _full(b'stco', struct.pack('>II', 1, chunk_offset)))
    dref = _full(b'dref', struct.pack('>I', 1) + _full(b'alis', b'', 1))
    gmhd = _box(b'gmhd', _full(b'gmin', struct.pack('>6H', 64, 32768, 32768, 32768, 0, 0)))
    minf = _box(b'minf', gmhd + _box(b'dinf', dref) + stbl)
    mdhd = _full(b'mdhd', struct.pack('>IIIIHH', 0, 0, TIMESCALE, FRAME_TICKS, 0x55C4, 0))
    name = b'Core Media Metadata'
    hdlr = _full(b'hdlr', b'mhlrmetaappl' + b'\0' * 8 + bytes([len(name)]) + name)
    mdia = _box(b'mdia', mdhd + hdlr + minf)
    start = round(still_ticks * scale / TIMESCALE)
    span = max(1, round(FRAME_TICKS * scale / TIMESCALE))
    edits = [(start, -1)] if start else []
    edits.append((span, 0))
    elst = _full(b'elst', struct.pack('>I', len(edits)) + b''.join(
        struct.pack('>IiI', duration, media_time, 65536) for duration, media_time in edits))
    matrix = struct.pack('>9i', 65536, 0, 0, 0, 65536, 0, 0, 0, 1073741824)
    tkhd = _full(b'tkhd', struct.pack('>5I', 0, 0, track_id, 0, start + span) +
                 b'\0' * 16 + matrix + b'\0' * 8, 3)
    return _box(b'trak', tkhd + _box(b'edts', elst) + mdia)


def _add_timed_metadata(path, still_ticks):
    data = path.read_bytes()
    roots = list(_boxes(data))
    moovs = [b for b in roots if b[0] == b'moov']
    if len(moovs) != 1 or not any(b[0] == b'mdat' for b in roots):
        raise ConversionError('Expected one movie and media data')
    _, moov, position, size = moovs[0]
    identifier = _read_movie_identifier(moov, allow_legacy=True)
    scale, _ = _movie_timing(moov)
    ids = []
    for kind, payload, _, _ in _boxes(moov):
        if kind == b'trak':
            tkhd = _child(payload, b'tkhd')
            ids.append(struct.unpack_from('>I', tkhd, 20 if tkhd[0] == 1 else 12)[0])
    track_id = max(ids, default=0) + 1
    children = []
    for kind, payload, _, _ in _boxes(moov):
        if kind == b'mvhd':
            payload = payload[:-4] + struct.pack('>I', track_id + 1)
        elif kind == b'meta':
            continue
        elif kind == b'udta':
            # FFmpeg puts mdta inside udta as an ISO fullbox. AVFoundation
            # pairing requires a movie-level QuickTime meta instead.
            payload = b''.join(_box(k, p) for k, p, _, _ in _boxes(payload) if k != b'meta')
            if not payload:
                continue
        children.append(_box(kind, payload))
    children.append(_content_identifier_meta(identifier))
    children.append(_metadata_track(track_id, scale, still_ticks, len(data) + 8))
    # Replace the old moov with equal-sized free space. Existing audio/video
    # chunk offsets remain valid even for fast-start input. No mdat is moved.
    output = (data[:position] + _box(b'free', b'\0' * (size - 8)) +
              data[position + size:] + _box(b'mdat', MARKER) +
              _box(b'moov', b''.join(children)))
    path.write_bytes(output)


def _write_identifier(jpg, identifier):
    value = identifier.encode('ascii') + b'\0'
    # Apple MakerNote offsets are relative to the start of the MakerNote.
    note = (APPLE_HEADER + struct.pack('>H', 1) +
            struct.pack('>HHII', 17, 2, len(value), 32) + b'\0' * 4 + value)
    exif = piexif.load(str(jpg))
    exif['Exif'][piexif.ExifIFD.MakerNote] = note
    piexif.insert(piexif.dump(exif), str(jpg))


def _read_identifier(jpg):
    with Image.open(jpg) as image:
        raw_exif = image.info.get('exif')
    if not raw_exif:
        raise ConversionError('Missing photo EXIF metadata')
    note = piexif.load(raw_exif)['Exif'].get(piexif.ExifIFD.MakerNote, b'')
    if not note.startswith(APPLE_HEADER):
        raise ConversionError('Missing Apple MakerNote')
    count = struct.unpack_from('>H', note, 14)[0]
    for i in range(count):
        tag, kind, length, offset = struct.unpack_from('>HHII', note, 16 + 12 * i)
        if tag == 17 and kind == 2 and offset + length <= len(note):
            value = note[offset:offset + length].rstrip(b'\0').decode('ascii')
            uuid.UUID(value)
            return value
    raise ConversionError('Missing photo content identifier')


def _content_identifier_meta(identifier):
    """Apple movie metadata is moov/meta, with NO fullbox version/flags."""
    handler = _full(b'hdlr', b'\0' * 4 + b'mdta' + b'\0' * 14)
    keys = _full(b'keys', struct.pack('>I', 1) + _box(b'mdta', CONTENT_KEY))
    value = _box(b'data', struct.pack('>II', 1, 0) + identifier.encode('ascii'))
    items = _box(b'ilst', _box(struct.pack('>I', 1), value))
    return _box(b'meta', handler + keys + items)


def _read_movie_identifier(moov, allow_legacy=False):
    metas = [p for k, p, _, _ in _boxes(moov) if k == b'meta']
    if allow_legacy:
        for k, p, _, _ in _boxes(moov):
            if k == b'udta':
                metas.extend(q for tag, q, _, _ in _boxes(p) if tag == b'meta')
    for meta in metas:
        # FFmpeg writes ISO fullbox meta; QuickTime also permits a plain atom.
        if meta[:4] == b'\0' * 4 and not allow_legacy:
            raise ConversionError('Apple movie-level meta must not be an ISO fullbox')
        body = meta[4:] if meta[:4] == b'\0' * 4 else meta
        keys = _child(body, b'keys')
        names = [p for _, p, _, _ in _boxes(keys[8:])]
        if CONTENT_KEY in names:
            index = names.index(CONTENT_KEY) + 1
            item = _child(_child(body, b'ilst'), struct.pack('>I', index))
            return _child(item, b'data')[8:].decode('utf-8')
    raise ConversionError('Missing Apple movie-level moov/meta content identifier (旧版文件需重新转换)')


def verify_live_photo(photo, video):
    """Validate our pair's identifiers, sample description, offsets and timing."""
    try:
        photo, video = Path(photo), Path(video)
        with Image.open(photo) as image:
            image.verify()
        identifier = _read_identifier(photo)
        data = video.read_bytes()
        moov = _child(data, b'moov')
        if _read_movie_identifier(moov) != identifier:
            raise ConversionError('Photo/video content identifiers do not match')
        scale, duration = _movie_timing(moov)
        valid_marker = False
        video_present = False
        for kind, track, _, _ in _boxes(moov):
            if kind != b'trak':
                continue
            handler = _path(track, b'mdia', b'hdlr')[8:12]
            video_present |= handler == b'vide'
            if handler != b'meta':
                continue
            stbl = _path(track, b'mdia', b'minf', b'stbl')
            entry = _child(_child(stbl, b'stsd')[8:], b'mebx')
            key = _child(_child(entry[8:], b'keys'), struct.pack('>I', 1))
            if _child(key, b'keyd') != b'mdta' + STILL_KEY:
                continue
            if _child(key, b'dtyp') != struct.pack('>II', 0, 65):
                raise ConversionError('Incorrect still-image-time data type')
            if _child(stbl, b'stsz')[4:] != struct.pack('>II', 9, 1):
                raise ConversionError('Invalid still-image-time sample size')
            offset = struct.unpack_from('>I', _child(stbl, b'stco'), 8)[0]
            if data[offset:offset + 9] != MARKER or not any(
                    k == b'mdat' and pos + 8 <= offset and offset + 9 <= pos + size
                    for k, _, pos, size in _boxes(data)):
                raise ConversionError('Invalid still-image-time sample offset')
            edits = _path(track, b'edts', b'elst')
            count = struct.unpack_from('>I', edits, 4)[0]
            start = struct.unpack_from('>I', edits, 8)[0] if count == 2 else 0
            if start >= duration:
                raise ConversionError('Still image timestamp lies outside movie')
            valid_marker = True
        if not video_present or not valid_marker:
            raise ConversionError('Missing video or still-image-time track')
        return {'valid': True, 'identifier': identifier, 'duration_seconds': duration / scale}
    except ConversionError:
        raise
    except (ValueError, KeyError, IndexError, struct.error, OSError) as exc:
        raise ConversionError(f'Invalid Live Photo pair: {exc}') from exc


def _run(ffmpeg, args):
    try:
        result = subprocess.run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin', '-y'] +
                                [str(a) for a in args], capture_output=True,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), timeout=300)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ConversionError(f'FFmpeg could not run: {exc}') from exc
    if result.returncode:
        raise ConversionError(result.stderr.decode('utf-8', errors='replace')[-2000:])


def convert_live_photo(source, output_dir, cover=None, max_duration=3.0, photo_format='heic', name_style='camera'):
    """Publish a verified HEIC/JPG + MOV pair atomically; never modify source.

    A supplied cover is retained visually (JPEG is not re-encoded); otherwise
    a middle video frame is used. max_duration limits the first motion segment.
    """
    source, output_dir = Path(source).resolve(), Path(output_dir).resolve()
    if photo_format not in ('heic', 'jpeg'):
        raise ConversionError('photo_format must be heic or jpeg')
    if name_style not in ('camera', 'original'):
        raise ConversionError('name_style must be camera or original')
    if not source.is_file():
        raise ConversionError(f'Source does not exist: {source}')
    if not math.isfinite(max_duration) or max_duration <= 0:
        raise ConversionError('max_duration must be positive')
    with source.open('rb') as handle:
        header = handle.read(12)
    if header[4:8] != b'ftyp':
        raise ConversionError('缓存不是 MP4/MOV 视频；请保留源文件供检查，不能仅修改后缀。')
    output_dir.mkdir(parents=True, exist_ok=True)
    identifier = str(uuid.uuid4()).upper()
    if name_style == 'camera':
        used = {p.stem.upper() for p in output_dir.glob('*/IMG_*.*')}
        number = next((i for i in range(1, 10000) if f'IMG_{i:04d}' not in used), None)
        if number is None:
            raise ConversionError('IMG_0001–IMG_9999 已用完，请选择新的输出目录')
        basename = f'IMG_{number:04d}'
    else:
        basename = source.stem if source.suffix.lower() != '.bin' else 'LivePhoto'
    destination = output_dir / (basename + '_' + identifier[:8])
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    with tempfile.TemporaryDirectory(prefix='.livephoto-', dir=output_dir) as temp:
        work = Path(temp)
        jpg, mov = work / (basename + '.JPG'), work / (basename + '.MOV')
        _run(ffmpeg, ['-i', source, '-t', str(max_duration), '-map', '0:v:0', '-map', '0:a:0?',
                      '-map_metadata', '-1', '-vf', 'scale=ceil(iw/2)*2:ceil(ih/2)*2,fps=30',
                      '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p',
                      '-c:a', 'aac', '-b:a', '192k', '-video_track_timescale', '600',
                      '-movie_timescale', '600', '-movflags', 'use_metadata_tags',
                      '-metadata', CONTENT_KEY.decode() + '=' + identifier, '-f', 'mov', mov])
        moov = _child(mov.read_bytes(), b'moov')
        video_track = next(track for kind, track, _, _ in _boxes(moov)
                           if kind == b'trak' and _path(track, b'mdia', b'hdlr')[8:12] == b'vide')
        sizes = _path(video_track, b'mdia', b'minf', b'stbl', b'stsz')
        frame_count = struct.unpack_from('>I', sizes, 8)[0]
        if frame_count < 2:
            raise ConversionError('视频不足两帧，无法生成动态实况照片')
        # Movie duration can be longer than video when the audio has a tail.
        frame = frame_count // 2
        still_ticks = frame * FRAME_TICKS
        if cover:
            with Image.open(cover) as image:
                if image.format == 'JPEG':
                    shutil.copyfile(cover, jpg)
                else:
                    from PIL import ImageOps
                    ImageOps.exif_transpose(image).convert('RGB').save(jpg, quality=95)
        else:
            _run(ffmpeg, ['-i', mov, '-vf', f'select=eq(n\\,{frame})',
                          '-frames:v', '1', '-q:v', '1', jpg])
        _write_identifier(jpg, identifier)
        photo = jpg
        if photo_format == 'heic':
            photo = work / (basename + '.HEIC')
            with Image.open(jpg) as image:
                image.save(photo, format='HEIF', quality=95, exif=image.info['exif'])
            jpg.unlink()
        _add_timed_metadata(mov, still_ticks)
        report = verify_live_photo(photo, mov)
        _run(ffmpeg, ['-xerror', '-i', mov, '-map', '0:v:0', '-map', '0:a:0?', '-f', 'null', '-'])
        report.update({'source': source.name, 'cover_source': Path(cover).name if cover else 'video frame',
                       'exporter_version': 'Apple-v4-AutoADB', 'photo_format': photo_format,
                       'still_time_seconds': still_ticks / TIMESCALE,
                       'max_duration_seconds': max_duration,
                       'device_tested': False})
        (work / 'manifest.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), 'utf-8')
        (work / '导入说明.txt').write_text(
            'HEIC（或 JPG）和同名 MOV 是一张 Live Photo 的配对资源，请勿拆开或改写元数据。\n'
            '推荐：将两个文件一起导入 macOS「照片」，再通过 iCloud 照片同步到 iPhone。\n'
            'Windows 到 iPhone 需要支持配对资源的 Live Photo 导入工具；普通文件复制或分别保存不能完成配对。\n'
            '已检查文件结构和视频解码，尚未在你的 iPhone 上验证。不是锁屏动态壁纸兼容性承诺。\n', 'utf-8')
        # Move all resources together only after verification. The temporary
        # directory itself remains for TemporaryDirectory's context cleanup.
        publish = work / 'pair'
        publish.mkdir()
        for item in list(work.iterdir()):
            if item != publish:
                item.rename(publish / item.name)
        publish.rename(destination)
    return {'photo': str(destination / photo.name), 'video': str(destination / mov.name),
            'identifier': identifier}
