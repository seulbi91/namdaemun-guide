#!/usr/bin/env python3
"""매장 사진을 앱용으로 줄이고, 위치정보(EXIF/GPS)를 지웁니다.

사용법
  pip install pillow            # iPhone HEIC 사진이면 pillow-heif 도 설치: pip install pillow-heif
  python tools/make_photos.py 내사진폴더            # → img/ 폴더에 WebP로 저장
  python tools/make_photos.py 내사진폴더 --out img --width 640 --quality 78

규칙
  · 직접 촬영했거나 사용 허락을 받은 사진만 넣으세요 (MEDIA_GUIDE.md 참고)
  · 파일 이름은 영문·숫자·하이픈으로 (예: chip-1.jpg, chip-2.jpg, chip-3.jpg)
  · 사람(특히 아이) 얼굴이 나온 사진은 쓰지 마세요 (이 도구는 얼굴을 찾아주지 않아요)
"""
import argparse, os, re, sys, collections
from PIL import Image, ImageOps
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except Exception:
    pass

EXT = {'.jpg', '.jpeg', '.png', '.webp', '.heic', '.heif'}

def slug(stem):
    s = re.sub(r'[^a-z0-9]+', '-', stem.lower()).strip('-')
    return s

def main():
    ap = argparse.ArgumentParser(description='매장 사진 줄이기 + 위치정보 제거')
    ap.add_argument('src', help='원본 사진이 들어 있는 폴더')
    ap.add_argument('--out', default='img', help='저장 폴더 (기본: img)')
    ap.add_argument('--width', type=int, default=640, help='가로 최대 픽셀 (기본 640)')
    ap.add_argument('--quality', type=int, default=78, help='WebP 품질 (기본 78)')
    a = ap.parse_args()

    if not os.path.isdir(a.src):
        sys.exit(f'폴더를 찾을 수 없어요: {a.src}')
    os.makedirs(a.out, exist_ok=True)
    files = [f for f in sorted(os.listdir(a.src)) if os.path.splitext(f)[1].lower() in EXT]
    if not files:
        sys.exit('변환할 사진(jpg, png, webp, heic)이 없어요.')

    done, used, skipped = [], set(), []
    for n, f in enumerate(files, 1):
        stem = slug(os.path.splitext(f)[0])
        if not stem:
            stem = f'photo-{n}'
            skipped.append(f'{f}: 한글 등 영문이 아닌 이름이라 {stem} 로 저장했어요 (이름을 영문으로 바꾸면 매장과 연결하기 쉬워요)')
        base, k = stem, 2
        while stem in used:
            stem = f'{base}-{k}'; k += 1
        used.add(stem)
        try:
            im = Image.open(os.path.join(a.src, f))
            had_gps = bool(im.getexif().get_ifd(0x8825))
            im = ImageOps.exif_transpose(im).convert('RGB')      # 회전 정보를 반영한 뒤 EXIF는 버림
            if im.width > a.width:
                im = im.resize((a.width, round(im.height * a.width / im.width)), Image.LANCZOS)
            out = os.path.join(a.out, stem + '.webp')
            im.save(out, 'WEBP', quality=a.quality, method=6)     # exif 인자를 주지 않으므로 메타데이터가 저장되지 않음
            clean = not Image.open(out).getexif()
            done.append((out, os.path.getsize(out) // 1024, had_gps, clean, im.size))
        except Exception as e:
            skipped.append(f'{f}: 변환 실패 ({e})')

    print(f'\n변환 완료: {len(done)}장 → {a.out}/')
    for out, kb, gps, clean, size in done:
        flag = ' ⚠ 용량이 큼(80KB 초과: --width 를 줄여 보세요)' if kb > 80 else ''
        print(f'  {os.path.basename(out):28} {size[0]}x{size[1]}  {kb}KB  위치정보 {"있었음→제거" if gps else "없음"}  확인:{"OK" if clean else "남아있음!"}{flag}')
    for s in skipped:
        print('  참고:', s)

    groups = collections.OrderedDict()
    for out, *_ in done:
        name = os.path.splitext(os.path.basename(out))[0]
        m = re.match(r'^(.*?)-?(\d+)$', name)
        groups.setdefault(m.group(1) if m else name, []).append(name)
    print('\n아래 줄을 index.html 의 MEDIA 안에 붙여 넣고, 앞의 이름을 실제 매장명으로 바꾸세요')
    print('(출처(credit)는 사실대로 적으세요: "직접 촬영" 또는 "@계정 (사용 허락 받음)")\n')
    for g, names in groups.items():
        ph = ','.join(f'{{src:"img/{x}.webp",alt:"{g} 사진 {i}",credit:"직접 촬영"}}' for i, x in enumerate(names[:3], 1))
        print(f'  "{g}":{{ig:"",photos:[{ph}]}},')
    if any(len(v) > 3 for v in groups.values()):
        print('\n  ※ 한 매장에는 사진 3장까지만 쓰여요.')

if __name__ == '__main__':
    main()
