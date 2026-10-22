"""Identify and convert media attachments for browser-friendly HTML output."""

import glob
import html
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlparse

from attachment_dedup import hash_media_file



def is_image_type(mime_type, filename):
    if mime_type and mime_type.startswith('image'):
        return True
    lower_name = filename.lower()
    return any(lower_name.endswith(ext) for ext in ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.heic', '.heif', '.heics'))


def is_video_type(mime_type, filename):
    if mime_type and mime_type.lower().startswith('video/'):
        return True
    return str(filename or '').lower().endswith(('.mov', '.mp4', '.m4v', '.3gp'))


def is_heic_type(mime_type, filename):
    lower_mime = str(mime_type or '').lower()
    lower_name = str(filename or '').lower()
    return (
        lower_mime in ('image/heic', 'image/heif', 'image/heic-sequence', 'image/heif-sequence', 'public.heic', 'public.heif')
        or lower_name.endswith(('.heic', '.heif', '.heics'))
    )


def _asset_url(path):
    return Path(os.path.abspath(path)).as_uri()


def _reuse_conversion(source_path, output_dir, conversion_folder, converted_path):
    if os.path.exists(converted_path):
        return True

    output_root = output_dir
    if os.path.basename(output_dir).startswith('extracted_backup_'):
        output_root = os.path.dirname(output_dir)
    pattern = os.path.join(
        output_root,
        'extracted_backup_*',
        conversion_folder,
        os.path.basename(converted_path),
    )
    for existing_path in sorted(glob.glob(pattern)):
        if os.path.normcase(existing_path) == os.path.normcase(converted_path):
            return True
        if not os.path.isfile(existing_path):
            continue
        os.makedirs(os.path.dirname(converted_path), exist_ok=True)
        temp_fd, temp_path = tempfile.mkstemp(
            prefix='.reuse_conversion_',
            dir=os.path.dirname(converted_path),
        )
        os.close(temp_fd)
        os.remove(temp_path)
        try:
            os.link(existing_path, temp_path)
            os.replace(temp_path, converted_path)
            return True
        except OSError as error:
            print(
                f'Could not reuse converted media "{existing_path}" for '
                f'"{source_path}"; converting again: {error}'
            )
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
    return False


def discover_attachment_folders(output_dir):
    attachment_folders = {}
    media_path_pattern = re.compile(
        r'MediaDomain[\\/]+Library[\\/]+SMS[\\/]+Attachments[\\/]+',
        re.IGNORECASE,
    )
    source_pattern = re.compile(
        r'<(?:img|source)\b[^>]*\bsrc="([^"]+)"',
        re.IGNORECASE,
    )

    for page_path in Path(output_dir).glob('*.html'):
        try:
            page_content = page_path.read_text(encoding='utf-8')
        except (OSError, UnicodeError):
            continue

        for match in source_pattern.finditer(page_content):
            source = html.unescape(match.group(1))
            if re.match(r'^[A-Za-z]:[\\/]', source):
                source_path = source
            else:
                parsed = urlparse(source)
                if parsed.scheme == 'file':
                    source_path = unquote(parsed.path.lstrip('/'))
                elif parsed.scheme:
                    continue
                else:
                    source_path = os.path.join(str(page_path.parent), unquote(source))

            media_match = media_path_pattern.search(source_path)
            if not media_match:
                continue

            media_domain_end = media_match.start() + len('MediaDomain')
            attachment_folder = os.path.join(
                source_path[:media_domain_end],
                'Library',
                'SMS',
                'Attachments',
            )
            if os.path.isdir(attachment_folder):
                absolute_folder = os.path.abspath(attachment_folder)
                attachment_folders[os.path.normcase(absolute_folder)] = absolute_folder

    return tuple(sorted(attachment_folders.values(), key=os.path.normcase))


def convert_heic_to_jpeg(source_path, output_dir):
    source_digest = hash_media_file(source_path, output_dir)
    preview_name = f'{source_digest}.jpg'
    preview_dir = os.path.join(output_dir, 'converted_heic')
    preview_path = os.path.join(preview_dir, preview_name)

    if _reuse_conversion(source_path, output_dir, 'converted_heic', preview_path):
        return preview_path

    try:
        import pillow_heif
        from PIL import Image, ImageOps
    except ImportError as exc:
        raise RuntimeError(
            'HEIC/HEIF attachments require Pillow and pillow-heif. '
            'Install them with: python -m pip install Pillow pillow-heif'
        ) from exc

    os.makedirs(preview_dir, exist_ok=True)
    pillow_heif.register_heif_opener()
    with Image.open(source_path) as image:
        ImageOps.exif_transpose(image).convert('RGB').save(preview_path, format='JPEG', quality=90)

    return preview_path


def convert_mov_to_mp4(source_path, output_dir):
    source_digest = hash_media_file(source_path, output_dir)
    video_name = f'{source_digest}.mp4'
    video_dir = os.path.join(output_dir, 'converted_mov')
    video_path = os.path.join(video_dir, video_name)

    if _reuse_conversion(source_path, output_dir, 'converted_mov', video_path):
        return video_path

    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise RuntimeError(
            'MOV conversion requires FFmpeg. Install it in your Conda environment with: '
            'conda install -c conda-forge ffmpeg'
        )

    os.makedirs(video_dir, exist_ok=True)
    temp_fd, temp_path = tempfile.mkstemp(suffix='.mp4', dir=video_dir)
    os.close(temp_fd)
    try:
        result = subprocess.run(
            [
                ffmpeg,
                '-y',
                '-analyzeduration', '100M',
                '-probesize', '100M',
                '-i', source_path,
                '-map', '0:v:0',
                '-map', '0:a:0?',
                '-c:v', 'libx264',
                '-preset', 'medium',
                '-crf', '23',
                '-pix_fmt', 'yuv420p',
                '-c:a', 'aac',
                '-b:a', '128k',
                '-movflags', '+faststart',
                temp_path,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            detail = result.stderr.strip() or 'FFmpeg returned an error without details.'
            raise RuntimeError(detail)
        os.replace(temp_path, video_path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

    return video_path


def format_attachment_html(
    attachment,
    base_dir,
    attachment_folder=None,
    conversion_failures=None,
    conversion_dir=None,
    fallback_attachment_folders=(),
):
    if conversion_failures is None:
        conversion_failures = {}

    filename = html.escape(str(attachment.get('filename') or 'attachment'))
    mime_type = attachment.get('mime_type') or ''
    file_path = attachment.get('file_path')
    conversion_dir = conversion_dir or attachment.get('conversion_dir') or base_dir
    size = attachment.get('file_size')

    info = []
    if mime_type:
        info.append(html.escape(mime_type))
    if size is not None:
        info.append(f"{size} bytes")
    info_text = ' | '.join(info)

    def normalize_path_text(raw_path):
        path = str(raw_path)
        if path.startswith('file://'):
            path = path[7:]
        return path.replace('\\', '/')

    if file_path:
        path_text = normalize_path_text(file_path)
        full_path = None

        if attachment_folder:
            # Try mapping iOS-style attachment paths to the configured attachment folder.
            relative_path = path_text.lstrip('/\\')
            candidate = os.path.normpath(os.path.join(attachment_folder, relative_path))
            if os.path.exists(candidate):
                full_path = candidate

            if not full_path and path_text.startswith('~/'):
                candidate = os.path.normpath(os.path.join(attachment_folder, path_text[2:]))
                if os.path.exists(candidate):
                    full_path = candidate

            if not full_path and 'Library/SMS/Attachments' in path_text:
                suffix = path_text.split('Library/SMS/Attachments', 1)[1].lstrip('/\\')
                candidate = os.path.normpath(os.path.join(attachment_folder, suffix))
                if os.path.exists(candidate):
                    full_path = candidate

            if not full_path and os.path.isabs(path_text):
                normalized = os.path.normpath(path_text)
                if os.path.exists(normalized):
                    full_path = normalized
                else:
                    just_filename = os.path.basename(path_text)
                    candidate = os.path.normpath(os.path.join(attachment_folder, just_filename))
                    if os.path.exists(candidate):
                        full_path = candidate

            if not full_path:
                just_filename = os.path.basename(path_text)
                candidate = os.path.normpath(os.path.join(attachment_folder, just_filename))
                if os.path.exists(candidate):
                    full_path = candidate

        if not full_path and os.path.exists(path_text):
            full_path = os.path.normpath(path_text)
        elif not full_path:
            expanded = os.path.expanduser(path_text)
            if expanded != path_text and os.path.exists(expanded):
                full_path = os.path.normpath(expanded)

        if not full_path:
            attachment_suffix = None
            for path_value in (file_path, attachment.get('filename')):
                if not path_value:
                    continue
                path_value = str(path_value).replace('\\', '/')
                for marker in (
                    'MediaDomain/Library/SMS/Attachments/',
                    'Library/SMS/Attachments/',
                ):
                    marker_index = path_value.casefold().find(marker.casefold())
                    if marker_index >= 0:
                        attachment_suffix = path_value[marker_index + len(marker):]
                        break
                if attachment_suffix:
                    break

            if attachment_suffix:
                for fallback_folder in fallback_attachment_folders:
                    candidate = os.path.join(fallback_folder, *attachment_suffix.split('/'))
                    if os.path.isfile(candidate):
                        full_path = candidate
                        break

        if full_path:
            if is_heic_type(mime_type, filename):
                failure_key = os.path.normcase(os.path.abspath(full_path))
                if failure_key not in conversion_failures:
                    try:
                        preview_path = convert_heic_to_jpeg(full_path, conversion_dir)
                    except (OSError, SyntaxError, ValueError) as exc:
                        conversion_failures[failure_key] = str(exc)
                        print(f'Warning: Could not convert HEIC/HEIF attachment "{full_path}": {exc}')
                    else:
                        src = _asset_url(preview_path)
                        return f'<div class="attachment"><img src="{html.escape(src)}" alt="{filename}" /></div>'

                return (
                    f'<div class="attachment"><span>{filename}</span>'
                    '<div class="attachment-meta">Preview unavailable (conversion failed).</div></div>'
                )

            src = _asset_url(full_path)
            if is_image_type(mime_type, filename):
                return f'<div class="attachment"><img src="{html.escape(src)}" alt="{filename}" /></div>'
            if is_video_type(mime_type, filename):
                video_path = full_path
                video_mime_type = mime_type
                if filename.lower().endswith('.mov'):
                    failure_key = f'mov:{os.path.normcase(os.path.abspath(full_path))}'
                    if failure_key not in conversion_failures:
                        try:
                            video_path = convert_mov_to_mp4(full_path, conversion_dir)
                        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
                            conversion_failures[failure_key] = str(exc)
                            print(f'Warning: Could not convert MOV attachment "{full_path}": {exc}')
                        else:
                            video_mime_type = 'video/mp4'
                    if failure_key in conversion_failures:
                        return (
                            f'<div class="attachment"><video controls preload="metadata">'
                            f'<source src="{html.escape(src)}" type="video/quicktime">'
                            'Your browser cannot play this video. '
                            f'<a href="{html.escape(src)}" target="_blank">{filename}</a>'
                            '</video><div class="attachment-meta">'
                            'MP4 conversion unavailable; try opening the original MOV.</div></div>'
                        )

                video_src = _asset_url(video_path)
                source_mime_type = (
                    video_mime_type
                    if video_mime_type.lower().startswith('video/')
                    else 'video/quicktime' if filename.lower().endswith('.mov') else 'video/mp4'
                )
                return (
                    f'<div class="attachment"><video controls preload="metadata">'
                    f'<source src="{html.escape(video_src)}" type="{html.escape(source_mime_type)}">'
                    'Your browser cannot play this video. '
                    f'<a href="{html.escape(video_src)}" target="_blank">{filename}</a>'
                    '</video></div>'
                )
            return f'<div class="attachment"><a href="{html.escape(src)}" target="_blank">{filename}</a><div class="attachment-meta">{info_text}</div></div>'

    return f'<div class="attachment"><span>{filename}</span><div class="attachment-meta">{info_text or "Attachment"}</div></div>'
