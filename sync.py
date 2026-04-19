import os, json, datetime, requests
import firebase_admin
from firebase_admin import credentials, firestore

# ── Config ──────────────────────────────────────────
EMAIL    = os.environ["XIAOMI_EMAIL"]
PASSWORD = os.environ["XIAOMI_PASSWORD"]
PROJECT  = os.environ["FIREBASE_PROJECT_ID"]
FB_KEY   = json.loads(os.environ["FIREBASE_KEY"])

# Data de hoje no horário de Brasília (UTC-3)
today = (datetime.datetime.utcnow() - datetime.timedelta(hours=3)).strftime("%Y-%m-%d")
today_ts = int(datetime.datetime.strptime(today, "%Y-%m-%d").timestamp() * 1000)

# ── Login Xiaomi/Zepp ────────────────────────────────
LOGIN_URL = "https://api-mifit-br2.zepp.com/v1/user/login"

def login():
    r = requests.post(LOGIN_URL, json={
        "email": EMAIL,
        "password": PASSWORD,
        "device_id": "github-action-sync"
    }, headers={"Content-Type": "application/json"}, timeout=15)
    data = r.json()
    if data.get("code") != 1000:
        raise Exception(f"Login falhou: {data}")
    return data["data"]["token"], data["data"]["userid"]

# ── Busca dados ──────────────────────────────────────
def get_health(token, userid):
    headers = {"apptoken": token, "userid": str(userid)}
    base = "https://api-mifit-br2.zepp.com"

    # FC em repouso
    hr_url = f"{base}/v1/data/band_data.json"
    hr_r = requests.get(hr_url, params={
        "query_type": "heart",
        "device_type": "0",
        "from_date": today,
        "to_date": today,
        "data_version": 6
    }, headers=headers, timeout=15)
    hr_data = hr_r.json()

    # Estresse
    stress_url = f"{base}/v1/data/band_data.json"
    stress_r = requests.get(stress_url, params={
        "query_type": "stress",
        "device_type": "0",
        "from_date": today,
        "to_date": today,
    }, headers=headers, timeout=15)
    stress_data = stress_r.json()

    return hr_data, stress_data

def parse_hr(hr_data):
    try:
        items = hr_data["data"]["items"]
        if not items: return None
        resting = [x["resting_heart_rate"] for x in items if x.get("resting_heart_rate")]
        return int(sum(resting) / len(resting)) if resting else None
    except Exception:
        return None

def parse_stress(stress_data):
    try:
        items = stress_data["data"]["items"]
        if not items: return None, None
        values = [x["stress_level"] for x in items if x.get("stress_level") is not None]
        if not values: return None, None
        avg = round(sum(values) / len(values))
        # reduz timeline para ~24 pontos
        step = max(1, len(values) // 24)
        timeline = values[::step][:24]
        return avg, timeline
    except Exception:
        return None, None

# ── Grava no Firestore ───────────────────────────────
def save(resting_hr, stress_avg, stress_timeline):
    cred = credentials.Certificate(FB_KEY)
    firebase_admin.initialize_app(cred)
    db = firestore.client()

    payload = {}
    if resting_hr is not None:
        payload["_mf_resting_hr"] = resting_hr
    if stress_avg is not None:
        payload["_mf_stress_avg"] = stress_avg
    if stress_timeline:
        payload["_mf_stress_timeline"] = stress_timeline

    if not payload:
        print("Nenhum dado encontrado para hoje.")
        return

    doc_ref = db.collection("dias").document(today)
    doc_ref.set(payload, merge=True)
    print(f"✅ Gravado em {today}: {payload}")

# ── Main ─────────────────────────────────────────────
if __name__ == "__main__":
    print(f"Sincronizando dados de {today}...")
    token, userid = login()
    hr_data, stress_data = get_health(token, userid)
    resting_hr = parse_hr(hr_data)
    stress_avg, stress_timeline = parse_stress(stress_data)
    save(resting_hr, stress_avg, stress_timeline)
