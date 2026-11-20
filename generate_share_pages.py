#!/usr/bin/env python3
"""
FORSA — generator halaman pratinjau berbagi (Open Graph) per artikel.

Mengapa perlu?
  WhatsApp/Facebook/Telegram tidak menjalankan JavaScript. Mereka hanya membaca
  tag <meta property="og:..."> di HTML awal. Situs FORSA dirender lewat JavaScript,
  jadi semua artikel tampak sama bagi mereka. Skrip ini membuat satu halaman kecil
  per artikel di  artikel/<slug>/index.html  yang berisi tag OG (judul, ringkasan,
  gambar). Pengunjung manusia langsung diarahkan ke  /?artikel=<slug>.

Pemakaian (jalankan di folder yang berisi index.html dan berita.json):
  python3 generate_share_pages.py --site https://domain-anda.com/

  --site   alamat publik situs (WAJIB, https, tanpa spasi). Jika situs ada di subfolder,
           sertakan, mis. https://user.github.io/forsa/
  --root   folder situs (default: folder saat ini)
  --json   nama file data berita (default: berita.json)

Jalankan ulang setiap kali berita baru ditambahkan atau judul diubah, lalu unggah
folder  artikel/  ke hosting. Gambar dikecilkan otomatis (maks. 1200px, <=300 KB)
jika Pillow terpasang:  pip install pillow
"""
import argparse, base64, html, io, json, mimetypes, os, re, sys, unicodedata

try:
    from PIL import Image
except ImportError:  # Pillow opsional
    Image = None

MAX_W, MAX_BYTES = 1200, 300 * 1024


def slugify(s):
    """Harus identik dengan slugify() di index.html."""
    s = unicodedata.normalize("NFD", str(s).lower())
    s = re.sub(r"[\u0300-\u036f]", "", s)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"^-+|-+$", "", s)[:80]
    return s or "artikel"


def make_slugs(items):
    """Harus identik dengan slugs() di index.html (judul kembar diberi -2, -3, ...)."""
    seen, out = {}, []
    for x in items:
        s = slugify(x.get("slug") or x.get("id") or x.get("judul", ""))
        seen[s] = seen.get(s, 0) + 1
        out.append(s if seen[s] == 1 else f"{s}-{seen[s]}")
    return out


def load_bytes(src, root):
    """Kembalikan bytes gambar dari data URI atau file lokal; None jika tidak bisa."""
    if src.startswith("data:image"):
        try:
            return base64.b64decode(src.split(",", 1)[1])
        except Exception:
            return None
    path = os.path.join(root, src.lstrip("/"))
    if os.path.isfile(path):
        with open(path, "rb") as f:
            return f.read()
    return None


def save_image(data, dest_base):
    """Simpan gambar (dioptimalkan bila ada Pillow). Kembalikan (nama_file, lebar, tinggi)."""
    if Image is None:
        ext = ".png" if data[:4] == b"\x89PNG" else ".jpg"
        with open(dest_base + ext, "wb") as f:
            f.write(data)
        if len(data) > MAX_BYTES:
            print(f"  ! {os.path.basename(dest_base)}{ext} {len(data)//1024} KB (>300 KB); "
                  "pasang Pillow agar otomatis dikecilkan", file=sys.stderr)
        return os.path.basename(dest_base) + ext, None, None
    im = Image.open(io.BytesIO(data))
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, "white")
        bg.paste(im, mask=im.split()[-1])
        im = bg
    else:
        im = im.convert("RGB")
    if im.width > MAX_W:
        im = im.resize((MAX_W, round(im.height * MAX_W / im.width)), Image.LANCZOS)
    q = 85
    while True:
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=q, optimize=True, progressive=True)
        if buf.tell() <= MAX_BYTES or q <= 50:
            break
        q -= 5
    with open(dest_base + ".jpg", "wb") as f:
        f.write(buf.getvalue())
    return os.path.basename(dest_base) + ".jpg", im.width, im.height


PAGE = """<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — FORSA</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="{url}">
<meta property="og:site_name" content="FORSA">
<meta property="og:locale" content="id_ID">
<meta property="og:type" content="article">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:url" content="{url}">
{image_tags}<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{title}">
<meta name="twitter:description" content="{desc}">
{twitter_image}<script>location.replace({target_js});</script>
</head>
<body style="font:16px/1.6 system-ui,sans-serif;max-width:560px;margin:15vh auto;padding:0 20px;text-align:center">
<p>Membuka artikel…</p>
<p><a href="{target}">Klik di sini jika tidak dialihkan otomatis.</a></p>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser(description="Buat halaman pratinjau berbagi per artikel FORSA")
    ap.add_argument("--site", required=True, help="alamat publik situs, mis. https://forsa.example.com/")
    ap.add_argument("--root", default=".")
    ap.add_argument("--json", default="berita.json")
    a = ap.parse_args()

    site = a.site.strip()
    if not re.match(r"^https?://[^\s]+$", site):
        sys.exit("--site harus berupa URL lengkap, mis. https://forsa.example.com/")
    if not site.endswith("/"):
        site += "/"
    root = os.path.abspath(a.root)
    jpath = os.path.join(root, a.json)
    if not os.path.isfile(jpath):
        sys.exit(f"{jpath} tidak ditemukan. Jalankan di folder situs atau pakai --root / --json.")
    with open(jpath, encoding="utf-8") as f:
        items = json.load(f)
    if not isinstance(items, list) or not items:
        sys.exit("berita.json kosong atau bukan array.")

    img_dir = os.path.join(root, "artikel", "img")
    os.makedirs(img_dir, exist_ok=True)

    # gambar cadangan: logo FORSA yang tertanam di index.html
    fallback = None
    ipath = os.path.join(root, "index.html")
    if os.path.isfile(ipath):
        m = re.search(r'<img[^>]+src="(data:image/[^"]+)"', open(ipath, encoding="utf-8").read())
        if m:
            data = load_bytes(m.group(1), root)
            if data:
                fallback = save_image(data, os.path.join(img_dir, "forsa-logo"))

    slugs = make_slugs(items)
    esc = lambda s: html.escape(str(s), quote=True)
    n_img = 0
    for x, slug in zip(items, slugs):
        title = str(x.get("judul", "")).strip() or "Artikel FORSA"
        desc = re.sub(r"\s+", " ", str(x.get("ringkasan") or "")).strip()
        if not desc:
            isi = x.get("isi") or []
            desc = re.sub(r"\s+", " ", " ".join(isi) if isinstance(isi, list) else str(isi)).strip()
        if len(desc) > 200:
            desc = desc[:197].rsplit(" ", 1)[0] + "…"
        desc = desc or "Baca selengkapnya di FORSA."

        img = None  # (url, w, h)
        g = str(x.get("gambar") or "").strip()
        if re.match(r"^https?://", g):
            img = (g, None, None)
        elif g:
            data = load_bytes(g, root)
            if data:
                name, w, h = save_image(data, os.path.join(img_dir, slug))
                img = (site + "artikel/img/" + name, w, h)
                n_img += 1
            else:
                print(f"  ! gambar untuk '{slug}' tidak ditemukan ({g[:60]}); pakai logo", file=sys.stderr)
        if img is None and fallback:
            img = (site + "artikel/img/" + fallback[0], fallback[1], fallback[2])

        url = f"{site}artikel/{slug}/"
        target = f"{site}?artikel={slug}"
        tags, tw = "", ""
        if img:
            tags = f'<meta property="og:image" content="{esc(img[0])}">\n'
            if img[0].startswith("https://"):
                tags += f'<meta property="og:image:secure_url" content="{esc(img[0])}">\n'
            if img[1]:
                tags += f'<meta property="og:image:width" content="{img[1]}">\n<meta property="og:image:height" content="{img[2]}">\n'
            tags += f'<meta property="og:image:alt" content="{esc(title)}">\n'
            tw = f'<meta name="twitter:image" content="{esc(img[0])}">\n'

        out_dir = os.path.join(root, "artikel", slug)
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8") as f:
            f.write(PAGE.format(title=esc(title), desc=esc(desc), url=esc(url), image_tags=tags,
                                twitter_image=tw, target=esc(target),
                                target_js=json.dumps(target).replace("</", "<\\/")))
        print(f"  ✓ {url}")

    print(f"\nSelesai: {len(items)} halaman, {n_img} gambar artikel. Unggah folder 'artikel/' ke hosting.")


if __name__ == "__main__":
    main()
