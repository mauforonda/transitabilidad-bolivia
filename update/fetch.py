#!/usr/bin/env python3

import requests
from requests_toolbelt.multipart.encoder import MultipartEncoder

from bs4 import BeautifulSoup

import re
import sys
import time
import random

import pandas as pd
import numpy as np

from datetime import datetime, timezone, timedelta


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
            lambda _: _.astype(str)
            .str.strip()
            .apply(lambda __: float(__) if __ else np.nan)
        )
        .round(5)
    )
    return df


DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko)",
    "Sec-Ch-Ua-Platform": "Linux",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Ch-Ua": '"Not_A Brand";v="99", "Chromium";v="142"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Accept": "*/*",
    "Origin": "https://www.proxydocker.com",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
    "Referer": "https://www.proxydocker.com/es/proxylist/country/Bolivia",
}


def _get_proxy_list():
    sess = requests.session()

    req = sess.get(
        "https://www.proxydocker.com/es/proxylist/country/Bolivia",
        headers=DEFAULT_HEADERS,
    )
    if "CAPTCHA Check" in req.text:
        time.sleep(1 + 3 * random.random())

        mp_encoder = MultipartEncoder({})
        req = sess.post(
            "https://www.proxydocker.com/api/captcha/check",
            data=mp_encoder,
            headers={**DEFAULT_HEADERS, "Content-Type": mp_encoder.content_type},
        )

        req = sess.get(
            "https://www.proxydocker.com/es/proxylist/country/Bolivia",
            headers=DEFAULT_HEADERS,
        )

    html = BeautifulSoup(req.content, "html.parser")

    meta = html.findChild("meta", attrs={"name": "_token"})
    token = meta.attrs["content"]

    PROXY_TYPES = {
        "1": "http",
        "2": "https",
        "12": "https",
        "3": "socks4",
        "4": "socks5",
    }

    proxy_data = {
        "token": token,
        "country": "Bolivia",
        "city": "all",
        "state": "all",
        "port": "all",
        "type": "all",
        "anonymity": "all",
        "need": "all",
        "page": 1,
    }
    proxies = []

    for page in range(1, 3):
        proxy_data["page"] = page
        req = sess.post(
            "https://www.proxydocker.com/es/api/proxylist/",
            data=proxy_data,
            headers={"X-Requested-With": "XMLHttpRequest", **DEFAULT_HEADERS},
        )

        payload = req.json()
        if "proxies" in payload and len(payload["proxies"]) > 0:
            proxies.extend(payload["proxies"])
        else:
            break

    proxies = [
        ("https", "{}://{}:{}".format(PROXY_TYPES[_["type"]], _["ip"], _["port"]))
        for _ in proxies
        if _["type"] in PROXY_TYPES.keys()
    ]

    return proxies


def _get_proxy_list2():
    def source_proxyhub():
        url = "https://proxyhub.me/en/bo-socks5-proxy-list.html"
        r = requests.get(url)
        html = BeautifulSoup(r.text, "html.parser")

        proxies = [
            {
                k: row.select("td")[v].get_text()
                for k, v in zip(["ip", "port", "type"], [0, 1, 2])
            }
            for row in html.select("tbody tr")
        ]
        return proxies

    def source_freeproxy():
        url = "https://www.freeproxy.world/?country=BO"
        r = requests.get(url)
        html = BeautifulSoup(r.text, "html.parser")

        proxies = [
            {
                k: row.select("td")[v].get_text().strip()
                for k, v in zip(["ip", "port", "type"], [0, 1, 5])
            }
            for row in html.select("tbody tr")
        ]
        return proxies

    def source_ditatompel():
        url = "https://www.ditatompel.com/proxy/country/bo"
        r = requests.get(url)
        html = BeautifulSoup(r.text, "html.parser")

        proxies = [
            {
                "ip": row.select("td")[0]
                .select("strong")[0]
                .get_text()
                .replace(":", ""),
                "port": row.select("td")[0].select("span")[0].get_text(),
                "type": row.select("td")[1].select("a")[0].get_text(),
            }
            for row in html.select("tbody tr")
        ]

        return proxies

    # proxies = sum([source_freeproxy(), source_proxyhub(), source_ditatompel()], [])
    proxies = source_freeproxy()
    return [("https", f"{p['type'].lower()}://{p['ip']}:{p['port']}") for p in proxies]


def proxy_request(url):
    proxies = _get_proxy_list()
    for proxy in proxies:
        proxy = dict([proxy])
        try:
            return requests.get(
                url,
                verify=False,
                proxies=proxy,
                headers=DEFAULT_HEADERS,
                timeout=20,
            )
        except Exception as e:
            print(f"Request error: {e}")
            continue

    raise Exception("non avail proxy")


def get_data(proxy=True, method="api"):
    def from_html(proxy):
        data = []
        url = "https://transitabilidad.abc.gob.bo/mapa"
        if proxy:
            html = proxy_request(url).text
        else:
            html = requests.get(url, verify=False).text
        popups = re.findall(r"\.bindPopup\(\'<img alt\=\"\" src\=.*", html)
        for popup in popups:
            if "youtube" not in popup:
                point = {}
                soup = BeautifulSoup("".join(popup.split("' + '")), "html.parser")
                fields = soup.select('b[style*="color: #f5b041"]')
                fields.extend(soup.select("b")[-2:])
                for field in fields:
                    point[normalize(field.get_text(), key=True)] = normalize(
                        str(field.next_sibling)
                    )
                data.append(point)
        if data:
            df = pd.DataFrame(data)
            df["fecha_consulta"] = now
            df["fecha_consulta"] = df["fecha_consulta"].dt.tz_localize(None)
            df["fecha_fin"] = ""
            df = format_columns(df)
            return df.sort_values(["fecha_reporte", "sección"])
        else:
            return None

    def from_api(proxy):
        def process_event(e):
            event = dict(
                fecha_consulta=now,
                fecha_reporte=e["fecha_registro_hora"],
                fecha_fin="",
                latitud=e["latitud_inicio_seccion"],
                longitud=e["longitud_inicio_seccion"],
                estado=normalize(
                    f"{e['estado']['codigo_estado']} - {e['estado']['descripcion_estado']}"
                ),
                sección=normalize(f"{e['inicio_seccion']} - {e['fin_seccion']}"),
                evento=normalize(e["evento"]["descripcion_evento"]),
                clima=normalize(e["clima"]["descripcion_clima"]),
                horario_de_corte=normalize(
                    e["horario_corte"]["descripcion_horario_de_corte"]
                ),
                tipo_de_carretera=normalize(
                    e["tipo_carretera"]["descripcion_tipo_carretera"]
                ),
                alternativa_de_circulación_o_desvios=normalize(
                    e["transitable_con_desvio"]["descripcion_transitable_con_desvio"]
                ),
                restricción_vehicular=normalize(
                    e["restriccion_vehicular"]["descripcion_restriccion_vehicular"]
                ),
                sector=normalize(e["descr_sector"]) if e["descr_sector"] else "",
                trabajos_de_conservación_vial=normalize(
                    e["trabajos_conservacion"]["descripcion_trabajos_conservacion_vial"]
                ),
            )
            return event

        url = "https://transitabilidad.abc.gob.bo/api/v1/data"
        print("Consultando eventos via API ...")
        if proxy:
            api = proxy_request(url).json()
        else:
            api = requests.get(
                url,
                verify=False,
                timeout=20,
            ).json()
        if api:
            print(f"Se registran {len(api)} eventos")
            data = [process_event(e) for e in api]
            df = pd.DataFrame(data)
            df["fecha_consulta"] = df["fecha_consulta"].dt.tz_localize(None)
            df["fecha_fin"] = ""
            df = format_columns(df)
            return df.sort_values(["fecha_reporte", "sección"])
        else:
            return None

    if method == "html":
        data = from_html(proxy)
    elif method == "api":
        data = from_api(proxy)
    else:
        data = None
    return data


def consolidate(df):
    print("Consolidando eventos ...")
    # retrieve saved entries
    oldf = pd.read_csv("data.csv", na_filter=False)
    oldf = format_columns(oldf)

    # compare entries and filter duplicates
    compare_cols = ["fecha_reporte", "latitud", "longitud"]
    joindf = pd.concat([oldf, df], axis=0, ignore_index=True)
    duplicates = joindf[joindf.duplicated(subset=compare_cols, keep="last")]

    # get entries that are not present in the newly fetched data
    expired = pd.concat([oldf, duplicates], axis=0, ignore_index=True)
    expired = expired[~expired.duplicated(subset=compare_cols, keep=False)]
    expired.loc[expired["fecha_fin"].isna(), ["fecha_fin"]] = now.replace(tzinfo=None)

    # get new entries
    new = pd.concat([df, duplicates], axis=0, ignore_index=True)
    new = new[~new.duplicated(subset=compare_cols, keep=False)]

    # join expired, duplicates and new entries

    finaldf = pd.concat(
        [expired, duplicates, new], axis=0, ignore_index=True
    ).sort_values(["fecha_reporte", "sección"])
    return format_columns(finaldf)


if __name__ == "__main__":
    now = datetime.now(timezone(timedelta(hours=-4)))
    try:
        try:
            print("Intentado una consulta directa ...")
            df = get_data(proxy=False, method="api")
        except Exception:
            print("Intentado una consulta via proxy ...")
            df = get_data(proxy=True, method="api")
    except (Exception, SystemExit):
        sys.exit("No puedo acceder al mapa")
    if df is not None:
        consolidate(df).to_csv(
            "data.csv",
            index=False,
            date_format="%Y-%m-%d %H:%M:%S",
            float_format="%.5f",
            columns=[
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
            ],
        )
