#!/usr/bin/env python3

import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from google import genai
from bs4 import BeautifulSoup
from io import BytesIO
from PIL import Image as PILImage


BASE_URL = "https://transitabilidad.abc.gob.bo"
API_URL = f"{BASE_URL}/api/v1/data"
DATA_PATH = Path("data.csv")
TIMEOUT = 30
MAX_FETCH_ATTEMPTS = 5

OUTPUT_COLUMNS = [
    "fecha_consulta",
    "fecha_reporte",
    "fecha_fin",
    "latitud",
    "longitud",
    "estado",
    "sección",
    "evento",
    "clima",
    "horario_de_corte",
    "tipo_de_carretera",
    "alternativa_de_circulación_o_desvios",
    "restricción_vehicular",
    "sector",
    "trabajos_de_conservación_vial",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64; rv:151.0) Gecko/20100101 Firefox/151.0"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": f"{BASE_URL}/",
    "X-Requested-With": "XMLHttpRequest",
}

GEMINI_KEY = os.environ["GEMINI_API_KEY"]
GEMINI_MODEL = "gemini-2.5-flash"


def normalize(text: str, key: bool = False):
    if key:
        text = text.replace(":", "").replace(" ", "_")
    return text.lower().strip()


def format_columns(df):
    col = {
        "dates": ["fecha_reporte", "fecha_consulta", "fecha_fin"],
        "category": [
            "estado",
            "evento",
            "clima",
            "horario_de_corte",
            "tipo_de_carretera",
            "alternativa_de_circulación_o_desvios",
            "restricción_vehicular",
            "trabajos_de_conservación_vial",
        ],
        "string": ["sección", "sector"],
        "float": ["latitud", "longitud"],
    }
    for field in col["dates"]:
        df[field] = pd.to_datetime(df[field].fillna(pd.NaT))
    df[col["category"]] = df[col["category"]].astype("category")
    df[col["string"]] = df[col["string"]].astype("string")

    df[col["float"]] = (
        df[col["float"]]
        .apply(
            lambda _: (
                _.astype(str).str.strip().apply(lambda __: float(__) if __ else np.nan)
            )
        )
        .round(5)
    )
    return df


def gemini_transcribe(session, image_url, headers, model):
    client = genai.Client(api_key=GEMINI_KEY)
    img_bytes = session.get(image_url, headers=headers).content
    image = PILImage.open(BytesIO(img_bytes))

    response = client.models.generate_content(
        model=model,
        contents=[
            "Transcribe this 6-character hexadecimal string shown in the image. Return exactly 6 characters, with no spaces, punctuation, markdown, or explanation.",
            image,
        ],
    )

    return response.text


def fetch_events():

    BASE = "https://transitabilidad.abc.gob.bo"

    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:151.0) Gecko/20100101 Firefox/151.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-GPC": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Priority": "u=0, i",
        "Pragma": "no-cache",
        "Cache-Control": "no-cache",
    }

    session = requests.Session()

    form = session.get(f"{BASE}/captcha-form", headers=headers)
    html = BeautifulSoup(form.text, "html.parser")
    captcha_url = html.select_one("#captcha-img")["src"]
    csrf_token = html.select_one('input[name="_token"]')["value"]
    captcha_text = gemini_transcribe(
        session,
        captcha_url,
        {**headers, "Referer": f"{BASE}/captcha-form"},
        GEMINI_MODEL,
    )
    print(captcha_text)
    captcha_response = session.post(
        f"{BASE}/captcha",
        headers={**headers, "Referer": f"{BASE}/captcha-form"},
        data={"_token": csrf_token, "captcha": captcha_text},
        allow_redirects=False,
    )
    home = session.get(f"{BASE}/", headers=headers)
    api_headers = {
        "User-Agent": headers["User-Agent"],
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": headers["Accept-Language"],
        "Referer": f"{BASE}/",
        "X-Requested-With": "XMLHttpRequest",
    }

    api = session.get(f"{BASE}/api/v1/data", headers=api_headers)
    if api.status_code == 200:
        return api.json()
    else:
        raise RuntimeError("Error fetching data")


def fetch_events_with_retries():
    last_error = None
    for attempt in range(1, MAX_FETCH_ATTEMPTS + 1):
        try:
            return fetch_events()
        except Exception as exc:
            last_error = exc
            if attempt < MAX_FETCH_ATTEMPTS:
                print(f"Intento {attempt} falló: {exc}")
                time.sleep(10)
    raise last_error


def event_to_row(event, now):
    return dict(
        fecha_consulta=now,
        fecha_reporte=event["fecha_registro_hora"],
        fecha_fin="",
        latitud=event["latitud_inicio_seccion"],
        longitud=event["longitud_inicio_seccion"],
        estado=normalize(
            f"{event['estado']['codigo_estado']} - "
            f"{event['estado']['descripcion_estado']}"
        ),
        sección=normalize(f"{event['inicio_seccion']} - {event['fin_seccion']}"),
        evento=normalize(event["evento"]["descripcion_evento"]),
        clima=normalize(event["clima"]["descripcion_clima"]),
        horario_de_corte=normalize(
            event["horario_corte"]["descripcion_horario_de_corte"]
        ),
        tipo_de_carretera=normalize(
            event["tipo_carretera"]["descripcion_tipo_carretera"]
        ),
        alternativa_de_circulación_o_desvios=normalize(
            event["transitable_con_desvio"]["descripcion_transitable_con_desvio"]
        ),
        restricción_vehicular=normalize(
            event["restriccion_vehicular"]["descripcion_restriccion_vehicular"]
        ),
        sector=normalize(event["descr_sector"]) if event["descr_sector"] else "",
        trabajos_de_conservación_vial=normalize(
            event["trabajos_conservacion"]["descripcion_trabajos_conservacion_vial"]
        ),
    )


def get_data(now):
    print("Consultando eventos via API ...")
    events = fetch_events_with_retries()
    print(f"Se registran {len(events)} eventos")

    df = pd.DataFrame(
        [event_to_row(event, now) for event in events],
        columns=OUTPUT_COLUMNS,
    )
    df["fecha_consulta"] = df["fecha_consulta"].dt.tz_localize(None)
    df["fecha_fin"] = ""
    df = format_columns(df)
    return df.sort_values(["fecha_reporte", "sección"])


def consolidate(df, now):
    print("Consolidando eventos ...")
    oldf = pd.read_csv(DATA_PATH, na_filter=False)
    oldf = format_columns(oldf)

    compare_cols = ["fecha_reporte", "latitud", "longitud"]
    joindf = pd.concat([oldf, df], axis=0, ignore_index=True)
    duplicates = joindf[joindf.duplicated(subset=compare_cols, keep="last")]

    expired = pd.concat([oldf, duplicates], axis=0, ignore_index=True)
    expired = expired[~expired.duplicated(subset=compare_cols, keep=False)]
    expired.loc[expired["fecha_fin"].isna(), ["fecha_fin"]] = now.replace(tzinfo=None)

    new = pd.concat([df, duplicates], axis=0, ignore_index=True)
    new = new[~new.duplicated(subset=compare_cols, keep=False)]

    finaldf = pd.concat(
        [expired, duplicates, new], axis=0, ignore_index=True
    ).sort_values(["fecha_reporte", "sección"])
    return format_columns(finaldf)


def write_data(df):
    df.to_csv(
        DATA_PATH,
        index=False,
        date_format="%Y-%m-%d %H:%M:%S",
        float_format="%.5f",
        columns=OUTPUT_COLUMNS,
    )


if __name__ == "__main__":
    now = datetime.now(timezone(timedelta(hours=-4)))
    try:
        data = get_data(now)
        write_data(consolidate(data, now))
    except Exception as exc:
        sys.exit(f"No puedo acceder a la API de transitabilidad: {exc}")
