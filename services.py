# Sheets + S3 + cache + helpers IO

# ============================================================
# 1
# ============================================================
def normalize_name(name: str) -> str:
    if not name:
        return ""
    s = str(name).lower().strip().replace("_", " ")
    while "  " in s:
        s = s.replace("  ", " ")
    return s

def display_name(name: str) -> str:
    if not name:
        return ""
    s = str(name).replace("_", " ").strip()
    while "  " in s:
        s = s.replace("  ", " ")
    return " ".join(w.capitalize() for w in s.split(" "))

def normalize_code(code: str) -> str:
    code = (code or "").strip().upper().replace(" ", "")
    return code.replace("O", "0")

def gen_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    a = "".join(random.choice(alphabet) for _ in range(4))
    b = "".join(random.choice(alphabet) for _ in range(4))
    return f"SUB-{a}-{b}"

# ============================================================
# 2
# ============================================================

def now_fr() -> datetime:
    return datetime.now(tz=PARIS_TZ)

def fmt_fr(dt: datetime) -> str:
    return dt.astimezone(PARIS_TZ).strftime("%d/%m %H:%M")

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

# ============================================================
# 3 CARTES VIP (S3 SIGNED URL + PNG)
# ============================================================
def get_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=AWS_ENDPOINT_URL if AWS_ENDPOINT_URL else None,
        aws_access_key_id=AWS_ACCESS_KEY_ID or None,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY or None,
        region_name=AWS_DEFAULT_REGION or "auto",
        config=Config(signature_version="s3v4"),
    )

def generate_signed_url(key: str, expires_seconds: int = 3600) -> Optional[str]:
    if not key or not AWS_S3_BUCKET_NAME:
        return None
    if not object_exists_in_bucket(key):
        return None
    s3 = get_s3_client()
    return s3.generate_presigned_url(
        ClientMethod="get_object",
        Params={"Bucket": AWS_S3_BUCKET_NAME, "Key": key},
        ExpiresIn=int(expires_seconds),
    )

def upload_png_to_bucket(png_bytes: bytes, object_key: str) -> str:
    if not AWS_S3_BUCKET_NAME:
        raise RuntimeError("AWS_S3_BUCKET_NAME manquant")

    s3 = get_s3_client()
    extra = {"ContentType": "image/png"}
    extra_try_acl = dict(extra)
    extra_try_acl["ACL"] = "public-read"

    try:
        s3.put_object(Bucket=AWS_S3_BUCKET_NAME, Key=object_key, Body=png_bytes, **extra_try_acl)
    except ClientError:
        s3.put_object(Bucket=AWS_S3_BUCKET_NAME, Key=object_key, Body=png_bytes, **extra)

    base = (AWS_ENDPOINT_URL or "").rstrip("/")
    return f"{base}/{AWS_S3_BUCKET_NAME}/{object_key}"

# ============================================================
# 4 Image
# ============================================================

def generate_vip_card_image(code_vip: str, full_name: str, dob: str, phone: str, bleeter: str) -> bytes:
    img = Image.open(VIP_TEMPLATE_PATH).convert("RGBA")
    draw = ImageDraw.Draw(img)

    title_font = ImageFont.truetype(VIP_FONT_PATH, 56)
    font_name  = ImageFont.truetype(VIP_FONT_PATH, 56)
    font_line  = ImageFont.truetype(VIP_FONT_PATH, 38)
    font_id    = ImageFont.truetype(VIP_FONT_PATH, 46)

    white  = (245, 245, 245, 255)
    red    = (220, 30, 30, 255)
    shadow = (0, 0, 0, 160)

    def shadow_text(x, y, text, font, fill):
        draw.text((x+2, y+2), text, font=font, fill=shadow)
        draw.text((x, y), text, font=font, fill=fill)

    # Titre VIP WINTER EDITION (centré)
    w, h = img.size
    vip_txt = "VIP"
    winter_txt = " WINTER EDITION"
    vip_w = draw.textlength(vip_txt, font=title_font)
    winter_w = draw.textlength(winter_txt, font=title_font)
    total_w = vip_w + winter_w
    x0 = int((w - total_w) / 2)
    y0 = 35
    shadow_text(x0, y0, vip_txt, title_font, red)
    shadow_text(x0 + vip_w, y0, winter_txt, title_font, white)

    full_name = display_name(full_name).upper()
    dob = (dob or "").strip()
    phone = (phone or "").strip()
    bleeter = (bleeter or "").strip()
    if bleeter and not bleeter.startswith("@"):
        bleeter = "@" + bleeter

    x = 70
    y = 140
    gap = 70

    shadow_text(x, y, full_name, font_name, white)
    shadow_text(x, y + gap*1, f"DN : {dob}", font_line, white)
    shadow_text(x, y + gap*2, f"TELEPHONE : {phone}", font_line, white)
    shadow_text(x, y + gap*3, f"BLEETER : {bleeter if bleeter else 'NON RENSEIGNE'}", font_line, white)

    card_text = f"CARD ID : {code_vip}"
    tw = draw.textlength(card_text, font=font_id)
    shadow_text(int((w - tw)/2), h - 95, card_text, font_id, red)

    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()

# ============================================================
# 5 Limites
# ============================================================

def extract_tag(text: str, prefix: str) -> Optional[str]:
    if not text:
        return None
    toks = text.lower().split()
    for tok in toks:
        if tok.startswith(prefix.lower()):
            return tok.split(":", 1)[1].strip() if ":" in tok else None
    return None

def parse_iso_dt(s: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.astimezone(PARIS_TZ)
    except Exception:
        return None

def last_friday_17(now: datetime) -> datetime:
    target_weekday = 4  # Friday
    candidate = now.replace(hour=17, minute=0, second=0, microsecond=0)
    days_back = (candidate.weekday() - target_weekday) % 7
    candidate = candidate - timedelta(days=days_back)
    if now < candidate:
        candidate -= timedelta(days=7)
    return candidate

def challenge_week_window(now: Optional[datetime] = None) -> Tuple[datetime, datetime]:
    now = now or now_fr()
    if now.tzinfo is None:
        now = now.replace(tzinfo=PARIS_TZ)

    bootstrap_end = parse_bootstrap_end()
    if bootstrap_end and now < bootstrap_end:
        start = last_friday_17(now)
        end = bootstrap_end
        return start, end

    start = last_friday_17(now)
    end = start + timedelta(days=7)
    return start, end

# ============================================================
# 6 Util Emoji
# ============================================================

def catify(text: str, chance: float = 0.20) -> str:
    if random.random() < chance:
        return f"{text} {random.choice(CAT_EMOJIS)}"
    return text

