"""Decode untrusted originals in a bounded subprocess."""
import json
import sys
import warnings


def decode(source, target):
    if sys.platform == 'linux':
        import resource
        for kind, limit in [(resource.RLIMIT_AS, 1536 * 1024**2), (resource.RLIMIT_CPU, 25),
                            (resource.RLIMIT_FSIZE, 30 * 1024**2), (resource.RLIMIT_CORE, 0)]:
            resource.setrlimit(kind, (limit, limit))
    from PIL import Image, ImageOps
    import pillow_heif
    pillow_heif.register_heif_opener(thumbnails=False, decode_threads=1)
    Image.MAX_IMAGE_PIXELS = 64_000_000
    warnings.simplefilter('error', Image.DecompressionBombWarning)
    with Image.open(source) as im:
        fmt = im.format
        if fmt not in ('JPEG', 'MPO', 'PNG', 'WEBP', 'HEIF'):
            raise ValueError('Use JPEG, PNG, WebP, HEIC, or HEIF.')
        if fmt == 'HEIF':
            # pillow-heif counts separate still images as animated frames. Its
            # opener already selects the container's declared primary image.
            # Sequence MIME types remain ineligible for this still-photo path.
            if getattr(im, 'custom_mimetype', '') not in ('image/heic', 'image/heif') or im.info.get('primary') is not True:
                raise ValueError('Select a HEIF still photo with a declared primary image.')
        elif fmt == 'MPO':
            # JPEG can contain extra still images, such as an HDR gain map.
            # Pillow exposes these as frames. Use the baseline photo at index 0,
            # as the original-image crop path does when it opens the same bytes.
            im.seek(0)
        elif getattr(im, 'is_animated', False):
            raise ValueError('Select a still photo.')
        def check_dimensions():
            if min(im.size) < 32 or max(im.size) > 16384 or im.width * im.height > 64_000_000:
                raise ValueError('The photo exceeds the dimension limit.')
        check_dimensions()
        im.load()
        # A decoder can refine the dimensions when it loads the primary pixels.
        check_dimensions()
        oriented = ImageOps.exif_transpose(im).convert('RGB')
        width, height = oriented.size
        oriented.thumbnail((2400, 2400))
        oriented.save(target, 'JPEG', quality=92)
    metadata = dict(format='JPEG' if fmt == 'MPO' else fmt, width=width, height=height)
    if fmt == 'MPO':
        metadata.update(container_format='MPO', primary_image_index=0)
    return metadata


if __name__ == '__main__':
    try:
        print(json.dumps(decode(sys.argv[1], sys.argv[2])))
    except Exception as exc:
        # The parent keeps these details in private diagnostics, not the API response.
        print(json.dumps({'error': 'The decoder could not read this photo.',
                          'error_type': type(exc).__name__, 'detail': str(exc)[:2000]}))
        sys.exit(1)
