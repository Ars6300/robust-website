import argparse
import base64
import collections
import gzip
import hashlib
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMGDIR = os.path.join(ROOT, "assets", "products")
DATADIR = os.path.join(ROOT, "assets", "data")
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")
BASE = "https://api.moysklad.ru/api/remap/1.2"
SEARCH = "ROBUST"
EXCLUDE = {"RS5803", "RB364231"}
MAX_PX = 760
WEBP_Q = 86
WORKERS = 6

IMAGE_INDEX = {
    "RB0102100": 1, "RB0102102": 1, "RB0102103": 1, "RB0102104": 1, "RB0102105": 1,
    "RB0273290": 2, "RB0273291": 2, "RB0273292": 1, "RB0273293": 2, "RB0273294": 3,
    "RB0273295": 2, "RB0273298": 2, "RB0273299": 1, "RB0273301": 2, "RB0273302": 2,
    "RB0273305": 3, "RB0273307": 2, "RB0273308": 1, "RB0273309": 1, "RB0273311": 2,
    "RB0273312": 2, "RB0273313": 2, "RB0273315": 2, "RB0273320": 2, "RB0273325": 2,
    "RB425LS": 1, "RB430LI": 1, "RB433LS": 2, "RB441W": 3, "RB4857L": 3,
    "RB444WK": 1, "RB486L": 3, "RB690LI": 1, "RB961LS": 3,
}

CATS = {
    "ТОРМОЗНАЯ СИСТЕМА": ("brakes", "Brake System"),
    "ПОДВЕСКА И РУЛЕВОЕ": ("suspension", "Suspension & Steering"),
    "ФИЛЬТРЫ ДЛЯ ГРУЗОВЫХ АВТО": ("filters", "Filters"),
    "КУЗОВ И КАБИНА": ("cab", "Cab & Body"),
    "ПНЕВМАТИЧЕСКАЯ СИСТЕМА": ("air", "Air System"),
    "АКСЕССУАРЫ": ("accessories", "Accessories"),
    "РАМА И ПЛАТФОРМА": ("chassis", "Chassis & Coupling"),
}

SUBS = {
    "Диски тормозные": "Brake Discs",
    "Колодки тормозные дисковые": "Brake Pads",
    "РМК СУППОРТА": "Caliper Repair Kits",
    "Тормозные камеры и энергоаккумуляторы": "Brake Chambers & Spring Brakes",
    "Фитинги": "Air Line Fittings",
    "Спиральные шланги": "Coiled Air Hoses",
    "Рычаги тормозные (трещотки)": "Slack Adjusters",
    "Амортизаторы подвески": "Suspension Shock Absorbers",
    "Сайлентблоки втулки, подушки": "Bushings & Mounts",
    "Фильтра воздушные": "Air Filters",
    "Фильтра салона": "Cabin Filters",
    "Фильтра топливные": "Fuel Filters",
    "Фильтра масляные": "Oil Filters",
    "Фильтра Влагоотделителя": "Air Dryer Cartridges",
    "Фильтра гидроусилителя": "Power Steering Filters",
    "Амортизаторы кабины": "Cab Shock Absorbers",
    "Краны и клапана": "Valves",
    "Безопасность": "Safety",
    "Стяжки груза": "Cargo Straps",
    "Седельно сцепное устройство": "Fifth Wheel",
}

DEFAULT_SUB = {"air": "Valves"}

SUB_ORDER = [
    "Brake Discs", "Brake Pads", "Brake Chambers & Spring Brakes",
    "Caliper Repair Kits", "Slack Adjusters", "Air Line Fittings", "Coiled Air Hoses",
    "Air Filters", "Cabin Filters", "Fuel Filters", "Oil Filters",
    "Air Dryer Cartridges", "Power Steering Filters",
    "Suspension Shock Absorbers", "Bushings & Mounts",
    "Cab Shock Absorbers", "Valves", "Fifth Wheel", "Cargo Straps", "Safety",
]

CAT_ORDER = ["Brake System", "Filters", "Suspension & Steering", "Cab & Body",
             "Air System", "Chassis & Coupling", "Accessories"]

TYPES = [
    ("Фильтрующий элемент топливного фильтра", "Fuel Filter Element"),
    ("Фильтрующий элемент масляного фильтра", "Oil Filter Element"),
    ("Фильтр влагоотделителя", "Air Dryer Cartridge"),
    ("Фильтр салона угольный", "Cabin Filter, Activated Carbon"),
    ("Фильтр гидроусилителя", "Power Steering Filter"),
    ("Фильтр топливный сепаратор", "Fuel Filter / Water Separator"),
    ("Фильтр воздушный", "Air Filter"),
    ("Фильтр салона", "Cabin Filter"),
    ("Фильтр топливный", "Fuel Filter"),
    ("Фильтр масляный", "Oil Filter"),
    ("Амортизатор кабины", "Cab Shock Absorber"),
    ("Амортизатор подвески прицепа", "Trailer Suspension Shock Absorber"),
    ("Амортизатор подвески", "Suspension Shock Absorber"),
    ("Колодка тормозная дисковая", "Disc Brake Pad Set"),
    ("Монтажный комплект тормозного диска", "Brake Disc Mounting Kit"),
    ("Диск тормозной", "Brake Disc"),
    ("Энергоаккумулятор", "Spring Brake Actuator"),
    ("Камера тормозная", "Brake Chamber"),
    ("Соединитель аварийный угловой", "Emergency Connector, Elbow"),
    ("Соединитель аварийный прямой", "Emergency Connector, Straight"),
    ("Соединитель аварийный тройник", "Emergency Connector, Tee"),
    ("Соединитель зубчатый прямой", "Barbed Connector, Straight"),
    ("Соединитель зубчатый тройник", "Barbed Connector, Tee"),
    ("Клапан уровня пола пневматической подвески", "Ride Height Control Valve"),
    ("Клапан перепускной пневматической системы", "Air System Overflow Valve"),
    ("Клапан управления тормозами прицепа аварийный", "Trailer Control Valve, Emergency"),
    ("Клапан ограничения давления", "Pressure Limiting Valve"),
    ("Основание осушителя воздуха", "Air Dryer Base with Governor"),
    ("Ремкомплект суппорта", "Caliper Repair Kit"),
    ("Клапан слива конденсата", "Condensate Drain Valve"),
    ("Клапан ускорительный тормозной системы", "Brake Relay Valve"),
    ("Клапан ускорительный", "Relay Valve"),
    ("Клапан быстрого растормаживания с двойным обратным клапаном",
     "Quick Release Valve with Double Check Valve"),
    ("Регулятор тормозного суппорта", "Brake Caliper Adjuster"),
    ("Вал регулировочный суппорта", "Caliper Adjusting Shaft"),
    ("Р/к направляющих суппорта", "Caliper Guide Repair Kit"),
    ("Р/к Суппорта", "Caliper Repair Kit"),
    ("Р/к Седла подкова", "Fifth Wheel Horseshoe Repair Kit"),
    ("Комплект рычагов суппорта", "Caliper Lever Kit"),
    ("Рычаг тормозной (трещотка) механический", "Slack Adjuster, Manual"),
    ("Рычаг тормозной (трещотка)", "Slack Adjuster"),
    ("Резьбовой фитинг штуцер", "Threaded Stud Fitting"),
    ("Переходник фитинг", "Fitting Adapter"),
    ("Фитинговое соединение", "Fitting Coupling"),
    ("Клапан контрольный резьбовой прямой", "Test Point Valve, Straight"),
    ("Сетчатый топливный фильтр", "Fuel Strainer"),
    ("Подушка балансира", "Balance Beam Bushing"),
    ("Шланг Спиральный", "Coiled Air Hose"),
    ("Стяжка груза", "Cargo Ratchet Strap"),
    ("Перчатки рабочие", "Work Gloves"),
    ("Палец сцепного устройства", "Fifth Wheel King Pin"),
]

TOKENS = [
    (r"комплект на ось", "axle set"),
    (r"\(\s*смен\.?\s*элем\.?\s*\)", "replaceable element"),
    (r"\bсмен\.?\s*элем\.?", "replaceable element"),
    (r"\(\s*сапуна\s*\)", "breather"),
    (r"\bгидроусилителя\b", "power steering"),
    (r"\bс\s+крышкой\b", "with cover"),
    (r"\bпластиковая\s+ручка\b", "plastic handle"),
    (r"\bзадние\b", "Rear"),
    (r"\bпередней\b", "Front"),
    (r"(\d+)\s*метров\b", r"\1 m"),
    (r"(\d+)\s*тонн\b", r"\1 t"),
    (r"(\d+)\s*м\.(?=\s|$)", r"\1 m"),
    (r"\bс\s+рмк\s+трубками\b", "with tube repair kit"),
    (r"\bбез\s+рмк\s+трубок\b", "without tube repair kit"),
    (r"\bс\s+маслоотделител\w*", "with oil separator"),
    (r"\bс\s+регулятором\s+давления\b", "with pressure governor"),
    (r"\bприцепы\s+и\s+полуприцепы\b", "trailers and semi-trailers"),
    (r"\bвтулка\s+(\d+)\s*мм", r"\1 mm bush"),
    (r"внутренний\s*/\s*наружный", "female/male"),
    (r"перед\.?\s*/\s*зад\.?", "Front/Rear"),
    (r"\bс\s+пруж(?:ин\w*|\.)?", "with spring"),
    (r"\bбез\s+пруж(?:ин\w*|\.)?", "without spring"),
    (r"\bбез\s+крышки\b", "without cover"),
    (r"\bбез\s+болтов\b", "without bolts"),
    (r"\bсо\s+штырем\b", "with pin"),
    (r"\bвтулка\s+короткая\b", "short bush"),
    (r"\bкалибровочный\s+болт\b", "calibration bolt"),
    (r"\bустановка\s+только\s+вертикально\b", "vertical mounting only"),
    (r"\bгоризонтальный\s*\(поперечный\)", "horizontal (transverse)"),
    (r"\bгоризонтальный\b", "horizontal"),
    (r"вентилир\w*", "vented"),
    (r"\bпод\s+датчик\b", "for sensor"),
    (r"\bпод\s+клинья\b", "for wedges"),
    (r"\bс\s+вилкой\b", "with clevis"),
    (r"\bс\s+монтажным\s+к[-\s]?[тT]ом\b", "with mounting kit"),
    (r"\bс\s+монтажным\s+комплектом\b", "with mounting kit"),
    (r"\bс\s+трубкой\b", "with tube"),
    (r"\bбайонетный\b", "bayonet"),
    (r"\bполиуретановый\b", "polyurethane"),
    (r"\bпластик\s*/\s*метал+\w*\b", "plastic/metal"),
    (r"\bметал+\w*\s*/\s*пластик\b", "metal/plastic"),
    (r"\bсоставная\b", "two-piece"),
    (r"\bс\s+болтами\b", "with bolts"),
    (r"\bпластик\b", "plastic"),
    (r"\bметал+\b", "metal"),
    (r"\bлатунь\b", "brass"),
    (r"\bчерные\b", "black"),
    (r"\bкрасный\b", "red"),
    (r"\bжелтый\b", "yellow"),
    (r"\bХ/Б\s+с\s+пвх\b", "cotton with PVC grip"),
    (r"\bпередн(?:ий|яя|ее|\.)", "Front"),
    (r"\bзадн(?:ий|яя|ее|\.)", "Rear"),
    (r"\bперед\.", "Front"),
    (r"\bзад\.", "Rear"),
    (r"\bправая\b", "Right"),
    (r"\bлевая\b", "Left"),
    (r"\bтип\b", "type"),
    (r"\bболт\s+сверху\b", "bolt-on top"),
    (r"\bотверстий\b", "holes"),
    (r"\bОт\b\.?|\bотв\b\.?|\bOтв\b\.?", "holes"),
    (r"мм\.?", " mm"),
    (r"\bсерия\b", "series"),
]

BRAND_ATTRS = [("Марка MAN", "MAN"), ("Марка ACTROS", "Actros"), ("Марка AXOR", "Axor"),
               ("Марка MERCEDES", "Mercedes-Benz"), ("Марка VOLVO", "Volvo"),
               ("Марка DAF", "DAF"), ("Марка SCANIA", "Scania"), ("Марка IVECO", "Iveco"),
               ("Марка прицепа BPW", "BPW"), ("Марка прицепа SAF", "SAF")]

NAME_BRANDS = [
    (r"\bMAN\b", "MAN"), (r"\bDAF\b", "DAF"), (r"\bVOLVO\b|\bVolvo\b", "Volvo"),
    (r"\bSCANIA\b|\bScania\b", "Scania"), (r"\bIVECO\b|\bIveco\b", "Iveco"),
    (r"\bMERCEDES\b|\bMercedes\b|\bACTROS\b|\bAXOR\b|\bATEGO\b|\bAROCS\b|\bANTOS\b|\bMB\b",
     "Mercedes-Benz"),
    (r"\bBPW\b", "BPW"), (r"\bSAF\b", "SAF"), (r"\bSCHMITZ\b|\bSchmitz\b", "Schmitz"),
    (r"\bRENAULT\b|\bRVI\b", "Renault"), (r"\bKNORR\b", "KNORR"), (r"\bWABCO\b", "WABCO"),
]

BLURB = {
    "Air Filters": "Traps dust and abrasive particles before they reach the intake, protecting cylinder bores and turbo components over long haul intervals.",
    "Cabin Filters": "Keeps road dust, soot and pollen out of the cab, keeping the driver alert and the HVAC evaporator clean.",
    "Fuel Filters": "Separates water and fine contamination from diesel before the injection system, guarding pumps and injectors against wear.",
    "Oil Filters": "Holds combustion soot and metal debris in suspension away from bearings, maintaining oil pressure through the full drain interval.",
    "Air Dryer Cartridges": "Removes moisture and oil vapour from compressed air, preventing corrosion and winter freeze-ups in the brake circuit.",
    "Power Steering Filters": "Filters the hydraulic circuit to protect the steering pump and gear from particle wear.",
    "Suspension Shock Absorbers": "Damps axle movement to keep tyres loaded on the road surface, shortening braking distance and reducing frame fatigue.",
    "Cab Shock Absorbers": "Controls cab movement on its air or coil mounts, cutting driver fatigue and protecting cab mounting points.",
    "Bushings & Mounts": "Locates the axle and absorbs shock loading between the beam and chassis, keeping geometry stable under load.",
    "Brake Discs": "Machined for even heat distribution and low run-out, giving stable pedal feel and predictable pad wear.",
    "Brake Pads": "Complete axle set with a friction compound matched to heavy commercial duty cycles and low disc aggression.",
    "Caliper Repair Kits": "Restores caliper travel and sealing so pad clearance stays correct and the caliper does not seize.",
    "Brake Chambers & Spring Brakes": "Converts air pressure into clamping force and holds the vehicle on the parking circuit when air is released.",
    "Air Line Fittings": "Connects and repairs pneumatic lines, holding a leak-free seal at full system working pressure.",
    "Coiled Air Hoses": "Flexible tractor-to-trailer air line that recoils clear of the fifth wheel without chafing.",
    "Slack Adjusters": "Maintains correct pushrod stroke as the lining wears, keeping braking balanced across the axle.",
    "Valves": "Controls and speeds air flow through the brake circuit for fast, even response at every wheel.",
    "Safety": "Workshop and driver protective equipment.",
    "Cargo Straps": "Secures the load to the deck with a rated ratchet mechanism.",
    "Fifth Wheel": "Coupling hardware machined to take the full drawbar and vertical load of the trailer.",
}

TYPE_BLURB = {
    "Brake Disc Mounting Kit": "Spring plates, retainers and bolts to seat the disc squarely on the hub and keep run-out within tolerance.",
    "Caliper Adjusting Shaft": "Restores the adjuster drive inside the caliper so pad clearance is taken up evenly as the lining wears.",
    "Caliper Guide Repair Kit": "Guide pins, bushes and boots that let the caliper slide freely instead of seizing and wearing one pad.",
    "Caliper Lever Kit": "Replaces the internal lever mechanism that transfers actuator force to the pads.",
    "Brake Caliper Adjuster": "Replacement adjuster assembly that keeps running clearance correct over the life of the pads.",
    "Fifth Wheel King Pin": "Machined coupling pin carrying the full vertical and drawbar load between tractor and trailer.",
    "Work Gloves": "Cotton glove with a PVC dotted grip for workshop and yard handling.",
    "Cargo Ratchet Strap": "Rated ratchet strap for securing loads to the deck.",
}

HOMO = str.maketrans({
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O",
    "Р": "P", "С": "C", "Т": "T", "Х": "X", "У": "Y",
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y",
})

LAT2CYR = str.maketrans({"a": "а", "c": "с", "e": "е", "o": "о", "p": "р", "x": "х",
                         "y": "у", "A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н",
                         "K": "К", "M": "М", "O": "О", "P": "Р", "T": "Т", "X": "Х"})

MODEL_CASE = {
    "actros": "Actros", "atego": "Atego", "axor": "Axor", "arocs": "Arocs",
    "antos": "Antos", "stralis": "Stralis", "trakker": "Trakker",
    "ecostralis": "EcoStralis", "cargobull": "Cargobull", "sprinter": "Sprinter",
    "euromover": "EuroMover", "cammondor": "Cammondor", "fruehauf": "Fruehauf",
    "schmitz": "Schmitz", "volvo": "Volvo", "mercedes": "Mercedes",
    "mercedes-benz": "Mercedes-Benz", "scania": "Scania", "iveco": "Iveco",
    "renault": "Renault", "mack": "Mack", "knorr": "KNORR", "wabco": "WABCO",
    "daf": "DAF", "man": "MAN", "bpw": "BPW", "saf": "SAF", "ror": "ROR",
    "rvi": "RVI", "euro": "Euro", "mm": "mm", "bar": "bar",
}

UPPER_WORDS = {"tga", "tgs", "tgx", "tgm", "tgl", "xf", "cf", "lf", "fh", "fm",
               "fmx", "fl", "sn6", "sn7", "sb7", "pan", "rh", "lh", "psi", "abs"}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def make_auth():
    login = os.environ.get("MS_LOGIN")
    pwd = os.environ.get("MS_PASSWORD")
    if not login or not pwd:
        sys.exit("Set MS_LOGIN and MS_PASSWORD environment variables first.")
    return base64.b64encode(f"{login}:{pwd}".encode()).decode()


def api(url, auth, as_json=True, attempts=4):
    headers = {"Authorization": "Basic " + auth, "Accept-Encoding": "gzip"}
    opener = urllib.request.build_opener(NoRedirect)
    for i in range(attempts):
        try:
            with opener.open(urllib.request.Request(url, headers=headers), timeout=90) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return json.loads(raw.decode("utf-8")) if as_json else raw
        except urllib.error.HTTPError as e:
            loc = e.headers.get("Location") if e.code in (301, 302, 303, 307) else None
            if loc:
                with urllib.request.urlopen(loc, timeout=120) as r:
                    raw = r.read()
                    return json.loads(raw.decode("utf-8")) if as_json else raw
            if e.code == 429 and i < attempts - 1:
                time.sleep(2 ** i)
                continue
            raise


def fetch_products(auth):
    rows, offset = [], 0
    while True:
        q = urllib.parse.urlencode({"search": SEARCH, "limit": 100, "offset": offset})
        res = api(f"{BASE}/entity/product?{q}", auth)
        rows.extend(res["rows"])
        if len(rows) >= res["meta"]["size"]:
            return rows
        offset += 100


def slug(code):
    return re.sub(r"[^A-Za-z0-9]+", "-", code).strip("-").lower()


def save_image(blob, dest):
    im = Image.open(io.BytesIO(blob))
    if im.mode in ("RGBA", "LA", "P"):
        bg = Image.new("RGB", im.size, (255, 255, 255))
        im = im.convert("RGBA")
        bg.paste(im, mask=im.split()[-1])
        im = bg
    else:
        im = im.convert("RGB")
    im.thumbnail((MAX_PX, MAX_PX), Image.LANCZOS)
    im.save(dest, "WEBP", quality=WEBP_Q, method=6)


def sync_images(rows, auth, full=False):
    os.makedirs(IMGDIR, exist_ok=True)
    os.makedirs(CACHE, exist_ok=True)
    stamp_path = os.path.join(CACHE, "image_stamps.json")
    stamps = {}
    if os.path.exists(stamp_path) and not full:
        stamps = json.load(open(stamp_path, encoding="utf-8"))

    targets = []
    for r in rows:
        code = (r.get("code") or "").strip()
        if not code or code.upper() in EXCLUDE:
            continue
        if r.get("images", {}).get("meta", {}).get("size", 0) < 1:
            continue
        targets.append((code, r["images"]["meta"]["href"]))

    def work(item):
        code, href = item
        dest = os.path.join(IMGDIR, slug(code) + ".webp")
        try:
            meta = api(href, auth)
        except Exception as e:
            return code, "meta-error", str(e)[:60]
        images = meta.get("rows") or []
        if not images:
            return code, "no-rows", ""
        pick = IMAGE_INDEX.get(code.upper(), 0)
        if pick >= len(images):
            pick = 0
        first = images[pick]
        stamp = f"{pick}:{first.get('updated', '')}"
        if not full and os.path.exists(dest) and stamps.get(code) == stamp:
            return code, "cached", stamp
        try:
            blob = api(first["meta"]["downloadHref"], auth, as_json=False)
            save_image(blob, dest)
        except Exception as e:
            return code, "download-error", str(e)[:60]
        return code, "written", stamp

    results = []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for res in ex.map(work, targets):
            results.append(res)

    counts = collections.Counter(r[1] for r in results)
    for code, status, stamp in results:
        if status in ("written", "cached"):
            stamps[code] = stamp
    json.dump(stamps, open(stamp_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for code, status, detail in results:
        if status.endswith("error") or status == "no-rows":
            print(f"  ! {code}: {status} {detail}")
    print(f"images: {counts.get('written', 0)} written, {counts.get('cached', 0)} unchanged")
    return counts


def attr(r, name):
    for a in r.get("attributes", []):
        if a.get("name") == name:
            v = a.get("value")
            if isinstance(v, dict):
                return v.get("name") or ""
            if isinstance(v, bool):
                return v
            return "" if v is None else str(v)
    return ""


def unmix(text):
    def fix(m):
        w = m.group(0)
        return w.translate(LAT2CYR) if re.search(r"[а-яё]", w, re.I) else w
    return re.sub(r"[A-Za-zА-Яа-яЁё]+", fix, text)


def clean_ru(name):
    s = re.sub(r"\(\s*ROBUST\s*\)", "", name, flags=re.I)
    s = re.sub(r"^\s*ROBUST\s+", "", s, flags=re.I)
    s = re.sub(r"\s+R[BS][0-9A-Z./]+\s*$", "", s)
    return re.sub(r"\s{2,}", " ", s).strip(" .")


def fix_case(word):
    core = word.strip("(),.")
    low = core.lower()
    if low in UPPER_WORDS:
        return word.replace(core, core.upper())
    if low in MODEL_CASE:
        return word.replace(core, MODEL_CASE[low])
    if re.fullmatch(r"[A-Za-z]{1,4}\d[\w./-]*", core) or re.fullmatch(r"\d+[A-Za-z]{1,4}", core):
        return word.replace(core, core.upper())
    return word


def translate_tail(tail):
    t = unmix(tail)
    for pat, rep in TOKENS:
        t = re.sub(pat, rep, t, flags=re.I)
    t = t.translate(HOMO)
    t = " ".join("/".join(fix_case(s) for s in w.split("/")) for w in t.split(" "))
    t = re.sub(r"\bMm\b", "mm", t)
    t = re.sub(r"(\d)\s*[Mm][Mm]\b", r"\1 mm", t)
    t = re.sub(r"\bSERIES\b", "Series", t)
    t = re.sub(r"\s{2,}", " ", t)
    t = re.sub(r"\s+([,.)])", r"\1", t)
    t = re.sub(r"\(\s*", "(", t)
    t = re.sub(r"\s*\)", ")", t)
    return t.strip(" ,.-")


def build_en(ru):
    base = unmix(clean_ru(ru))
    low = base.lower()
    for ru_type, en_type in TYPES:
        if low.startswith(ru_type.lower()):
            return en_type, translate_tail(base[len(ru_type):].strip(" ,.-"))
    return None, translate_tail(base)


def brands_from_text(txt):
    t = txt.translate(HOMO).upper()
    found = []
    for pat, name in NAME_BRANDS:
        if re.search(pat, t, flags=re.I) and name not in found:
            found.append(name)
    return found


def image_url(code):
    path = os.path.join(IMGDIR, slug(code) + ".webp")
    if not os.path.exists(path):
        return ""
    digest = hashlib.md5(open(path, "rb").read()).hexdigest()[:8]
    return f"assets/products/{slug(code)}.webp?v={digest}"


def sub_rank(name):
    return SUB_ORDER.index(name) if name in SUB_ORDER else 99


def build_catalog(rows, generated):
    out, untyped = [], []
    for r in rows:
        code = (r.get("code") or "").strip()
        if not code or code.upper() in EXCLUDE:
            continue
        img = image_url(code)
        if not img:
            continue
        ru = r.get("name", "")
        en_type, tail = build_en(ru)
        if en_type is None:
            untyped.append(ru)
            en_type, tail = clean_ru(ru), ""
        parts = (r.get("pathName") or "").split("/")
        top = parts[0]
        sub_ru = parts[-1] if len(parts) > 1 else top
        cat_id, cat_name = CATS.get(top, ("other", "Other"))
        sub_name = SUBS.get(sub_ru, DEFAULT_SUB.get(cat_id, cat_name))
        brands = brands_from_text(ru)
        for ru_attr, en in BRAND_ATTRS:
            if attr(r, ru_attr) is True:
                en = "Mercedes-Benz" if en in ("Actros", "Axor") else en
                if en not in brands:
                    brands.append(en)
        art = (r.get("article") or "").strip()
        seen, crosses = set(), []
        for c in re.split(r"[/|]", art):
            c = c.strip()
            if c and c.upper() != code.upper() and c.upper() not in seen:
                seen.add(c.upper())
                crosses.append(c)
        out.append({
            "code": code,
            "name": en_type if not tail else f"{en_type} — {tail}",
            "type": en_type,
            "fitment": tail,
            "nameRu": clean_ru(ru),
            "category": cat_id,
            "categoryName": cat_name,
            "sub": sub_name,
            "brands": brands,
            "blurb": TYPE_BLURB.get(en_type, BLURB.get(sub_name, "")),
            "crosses": crosses[:40],
            "crossCount": len(crosses),
            "image": img,
        })

    out.sort(key=lambda p: (CAT_ORDER.index(p["categoryName"]) if p["categoryName"] in CAT_ORDER else 99,
                            sub_rank(p["sub"]), p["type"], p["fitment"]))

    grouped = collections.OrderedDict()
    for p in out:
        grouped.setdefault(p["categoryName"], collections.Counter())[p["sub"]] += 1
    tree = []
    for name in CAT_ORDER:
        if name not in grouped:
            continue
        cid = next(p["category"] for p in out if p["categoryName"] == name)
        tree.append({
            "id": cid, "name": name, "count": sum(grouped[name].values()),
            "subs": [{"name": s, "count": grouped[name][s]}
                     for s in sorted(grouped[name], key=sub_rank)],
        })

    os.makedirs(DATADIR, exist_ok=True)
    data = {"generated": generated, "total": len(out), "categories": tree, "products": out}
    with open(os.path.join(DATADIR, "products.json"), "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    return out, tree, untyped


def main():
    ap = argparse.ArgumentParser(description="Sync Robust catalogue from MoySklad.")
    ap.add_argument("--full", action="store_true",
                    help="re-download every image instead of only changed ones")
    ap.add_argument("--no-images", action="store_true",
                    help="rebuild products.json from images already on disk")
    args = ap.parse_args()

    auth = make_auth()
    print("fetching product list...")
    rows = fetch_products(auth)
    print(f"products in MoySklad matching '{SEARCH}': {len(rows)}")
    os.makedirs(CACHE, exist_ok=True)
    with open(os.path.join(CACHE, "products_raw.json"), "w", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False)

    if not args.no_images:
        sync_images(rows, auth, full=args.full)

    keep = {slug(c) + ".webp" for c in
            ((r.get("code") or "").strip() for r in rows) if c and c.upper() not in EXCLUDE}
    orphans = [f for f in os.listdir(IMGDIR) if f.endswith(".webp") and f not in keep]
    for f in orphans:
        os.remove(os.path.join(IMGDIR, f))
    if orphans:
        print(f"pruned {len(orphans)} image(s) no longer in MoySklad: {', '.join(orphans)}")

    import datetime
    stamp = datetime.date.today().isoformat()
    out, tree, untyped = build_catalog(rows, stamp)

    print(f"\ncatalogue: {len(out)} products, {len(tree)} categories")
    for c in tree:
        print(f"  {c['name']} ({c['count']})")
    cyr = [p["code"] for p in out if re.search(r"[а-яА-ЯёЁ]", p["name"])]
    if untyped:
        print(f"\nNO ENGLISH NAME RULE ({len(untyped)}) - add to TYPES in this file:")
        for u in untyped:
            print("   ", u)
    if cyr:
        print(f"\nRUSSIAN LEFT IN NAME ({len(cyr)}) - add to TOKENS in this file: {cyr}")
    if not untyped and not cyr:
        print("all names translated cleanly")


if __name__ == "__main__":
    main()
