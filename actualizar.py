#!/usr/bin/env python3
"""Actualiza `data.csv` con los eventos de transitabilidad vigentes de la ABC.

Cada corrida:
1. Resuelve el captcha de https://transitabilidad.abc.gob.bo con Gemini.
2. Descarga los eventos vigentes desde la API.
3. Los consolida con el histórico en `data.csv`:
   - un evento nuevo se agrega con `fecha_consulta` igual a la hora de la corrida;
   - un evento que sigue vigente no cambia;
   - un evento abierto que ya no aparece recibe `fecha_fin` igual a la hora de la corrida.
4. Actualiza `datapackage.json` y las cifras de cobertura de `readme.md`.

Un evento se identifica con (`fecha_reporte`, `latitud`, `longitud`).

Uso:
    GEMINI_API_KEY=... python actualizar.py
"""

import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

import pandas as pd
import requests
import urllib3
from bs4 import BeautifulSoup
from google import genai
from PIL import Image

# --- Configuración -----------------------------------------------------------

URL_BASE = "https://transitabilidad.abc.gob.bo"
RUTA_DATOS = Path(__file__).resolve().parent / "data.csv"
RUTA_PAQUETE = RUTA_DATOS.with_name("datapackage.json")
ZONA_HORARIA = timezone(timedelta(hours=-4))  # Bolivia no usa horario de verano
TIMEOUT = 30  # segundos por petición HTTP
INTENTOS = 5
ESPERA_ENTRE_INTENTOS = 10  # segundos
MODELO_GEMINI = "gemini-3.1-flash-lite"
FORMATO_FECHA = "%Y-%m-%d %H:%M:%S"
PATRON_CAPTCHA = re.compile(r"[0-9a-f]{6}")

# El certificado TLS de la fuente venció el 2026-11-15 y el servidor no lo ha
# renovado. Los datos son públicos y no enviamos credenciales, así que omitimos
# la verificación. Cambiar a True cuando la fuente renueve su certificado.
VERIFICAR_TLS = False

# Columnas de `data.csv`, en orden, agrupadas por tipo.
COLUMNAS_FECHA = ["fecha_consulta", "fecha_reporte", "fecha_fin"]
COLUMNAS_COORDENADA = ["latitud", "longitud"]
COLUMNAS_TEXTO = [
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
COLUMNAS = COLUMNAS_FECHA + COLUMNAS_COORDENADA + COLUMNAS_TEXTO
CLAVE = ["fecha_reporte", "latitud", "longitud"]

HEADERS_NAVEGADOR = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:151.0) Gecko/20100101 Firefox/151.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
HEADERS_API = {
    "User-Agent": HEADERS_NAVEGADOR["User-Agent"],
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": HEADERS_NAVEGADOR["Accept-Language"],
    "Referer": f"{URL_BASE}/",
    "X-Requested-With": "XMLHttpRequest",
}


# --- Descarga ----------------------------------------------------------------


def resolver_captcha(sesion: requests.Session, url_imagen: str) -> str:
    """Transcribe con Gemini el captcha (6 caracteres hexadecimales)."""
    respuesta = sesion.get(
        url_imagen,
        headers={**HEADERS_NAVEGADOR, "Referer": f"{URL_BASE}/captcha-form"},
        timeout=TIMEOUT,
    )
    respuesta.raise_for_status()
    imagen = Image.open(BytesIO(respuesta.content))

    # El cliente debe seguir referenciado durante la petición: si se descarta,
    # Python lo cierra y la llamada falla con "the client has been closed".
    with genai.Client(api_key=os.environ["GEMINI_API_KEY"]) as cliente:
        resultado = cliente.models.generate_content(
            model=MODELO_GEMINI,
            contents=[
                (
                    "Transcribe this 6-character hexadecimal string shown in the "
                    "image. Return exactly 6 characters, with no spaces, "
                    "punctuation, markdown, or explanation."
                ),
                imagen,
            ],
        )
    texto = (resultado.text or "").strip().lower()
    if not PATRON_CAPTCHA.fullmatch(texto):
        raise RuntimeError(f"Transcripción de captcha inválida: {texto!r}")
    return texto


def descargar_eventos_una_vez() -> list[dict]:
    """Pasa el captcha y descarga la lista de eventos vigentes (un intento)."""
    sesion = requests.Session()
    sesion.verify = VERIFICAR_TLS
    if not VERIFICAR_TLS:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    formulario = sesion.get(
        f"{URL_BASE}/captcha-form", headers=HEADERS_NAVEGADOR, timeout=TIMEOUT
    )
    formulario.raise_for_status()
    html = BeautifulSoup(formulario.text, "html.parser")
    imagen = html.select_one("#captcha-img")
    token = html.select_one('input[name="_token"]')
    if imagen is None or token is None:
        raise RuntimeError("El formulario de captcha no tiene la estructura esperada")

    texto = resolver_captcha(sesion, imagen["src"])
    sesion.post(
        f"{URL_BASE}/captcha",
        headers={**HEADERS_NAVEGADOR, "Referer": f"{URL_BASE}/captcha-form"},
        data={"_token": token["value"], "captcha": texto},
        allow_redirects=False,
        timeout=TIMEOUT,
    )
    sesion.get(f"{URL_BASE}/", headers=HEADERS_NAVEGADOR, timeout=TIMEOUT)

    respuesta = sesion.get(
        f"{URL_BASE}/api/v1/data", headers=HEADERS_API, timeout=TIMEOUT
    )
    if respuesta.status_code != 200:
        raise RuntimeError(f"La API respondió con código {respuesta.status_code}")
    eventos = respuesta.json()
    if not isinstance(eventos, list) or not eventos:
        # Una lista vacía cerraría todos los eventos abiertos: la tratamos como error.
        raise RuntimeError("La API no devolvió una lista de eventos")
    return eventos


def descargar_eventos() -> list[dict]:
    """Descarga los eventos vigentes y reintenta si falla."""
    for intento in range(1, INTENTOS + 1):
        try:
            return descargar_eventos_una_vez()
        except Exception as error:
            print(f"Intento {intento}/{INTENTOS} falló: {error}", file=sys.stderr)
            if intento == INTENTOS:
                raise
            time.sleep(ESPERA_ENTRE_INTENTOS)


# --- Transformación ----------------------------------------------------------


def normalizar(texto: str | None) -> str:
    """Pasa a minúsculas y quita espacios en los extremos."""
    return (texto or "").lower().strip()


def evento_a_fila(evento: dict, ahora: datetime) -> dict:
    """Convierte un evento de la API en una fila con las columnas de `data.csv`."""
    return {
        "fecha_consulta": ahora,
        "fecha_reporte": evento["fecha_registro_hora"],
        "fecha_fin": None,
        "latitud": evento["latitud_inicio_seccion"],
        "longitud": evento["longitud_inicio_seccion"],
        "estado": normalizar(
            f"{evento['estado']['codigo_estado']} - "
            f"{evento['estado']['descripcion_estado']}"
        ),
        "sección": normalizar(f"{evento['inicio_seccion']} - {evento['fin_seccion']}"),
        "evento": normalizar(evento["evento"]["descripcion_evento"]),
        "clima": normalizar(evento["clima"]["descripcion_clima"]),
        "horario_de_corte": normalizar(
            evento["horario_corte"]["descripcion_horario_de_corte"]
        ),
        "tipo_de_carretera": normalizar(
            evento["tipo_carretera"]["descripcion_tipo_carretera"]
        ),
        "alternativa_de_circulación_o_desvios": normalizar(
            evento["transitable_con_desvio"]["descripcion_transitable_con_desvio"]
        ),
        "restricción_vehicular": normalizar(
            evento["restriccion_vehicular"]["descripcion_restriccion_vehicular"]
        ),
        "sector": normalizar(evento["descr_sector"]),
        "trabajos_de_conservación_vial": normalizar(
            evento["trabajos_conservacion"]["descripcion_trabajos_conservacion_vial"]
        ),
    }


def dar_formato(tabla: pd.DataFrame) -> pd.DataFrame:
    """Aplica tipos a las columnas, redondea coordenadas y elimina duplicados."""
    tabla = tabla[COLUMNAS].copy()
    for columna in COLUMNAS_FECHA:
        tabla[columna] = pd.to_datetime(tabla[columna], format="ISO8601").astype(
            "datetime64[s]"
        )
    for columna in COLUMNAS_COORDENADA:
        tabla[columna] = pd.to_numeric(tabla[columna], errors="coerce").round(5)
    for columna in COLUMNAS_TEXTO:
        tabla[columna] = tabla[columna].fillna("").astype(str)
    tabla = tabla.drop_duplicates(subset=CLAVE, keep="first")
    return tabla.sort_values(["fecha_reporte", "sección"], kind="stable").reset_index(
        drop=True
    )


def claves(tabla: pd.DataFrame) -> pd.Series:
    """Identificador textual de cada evento, estable al guardar y leer el CSV."""
    return (
        tabla["fecha_reporte"].dt.strftime(FORMATO_FECHA)
        + "|"
        + tabla["latitud"].map("{:.5f}".format)
        + "|"
        + tabla["longitud"].map("{:.5f}".format)
    )


# --- Consolidación -----------------------------------------------------------


def leer_historico() -> pd.DataFrame:
    """Lee `data.csv` o devuelve una tabla vacía si no existe."""
    if not RUTA_DATOS.exists():
        return dar_formato(pd.DataFrame(columns=COLUMNAS))
    historico = pd.read_csv(RUTA_DATOS, keep_default_na=False, na_values=[""])
    faltantes = set(COLUMNAS) - set(historico.columns)
    if faltantes:
        raise RuntimeError(f"A data.csv le faltan columnas: {sorted(faltantes)}")
    return dar_formato(historico)


def consolidar(
    historico: pd.DataFrame, vigentes: pd.DataFrame, ahora: datetime
) -> pd.DataFrame:
    """Combina el histórico con los eventos vigentes.

    - Los eventos del histórico se conservan sin cambios, aunque reaparezcan.
    - Los eventos vigentes que no están en el histórico se agregan.
    - Los eventos abiertos del histórico que ya no están vigentes se cierran.
    """
    claves_vigentes = set(claves(vigentes))
    claves_historico = claves(historico)

    cierra = historico["fecha_fin"].isna() & ~claves_historico.isin(claves_vigentes)
    historico = historico.copy()
    historico.loc[cierra, "fecha_fin"] = pd.Timestamp(ahora)

    nuevos = vigentes[~claves(vigentes).isin(set(claves_historico))]
    nuevos = nuevos.astype(historico.dtypes.to_dict())
    print(f"Eventos nuevos: {len(nuevos)}; eventos cerrados: {int(cierra.sum())}")
    return dar_formato(pd.concat([historico, nuevos], ignore_index=True))


def guardar(tabla: pd.DataFrame) -> None:
    """Escribe `data.csv` completo o no lo toca (escritura atómica)."""
    temporal = RUTA_DATOS.with_suffix(".csv.tmp")
    tabla.to_csv(
        temporal,
        index=False,
        date_format=FORMATO_FECHA,
        float_format="%.5f",
        columns=COLUMNAS,
    )
    os.replace(temporal, RUTA_DATOS)


def actualizar_metadatos(tabla: pd.DataFrame, ahora: datetime) -> None:
    """Actualiza en `datapackage.json` los campos que cambian en cada corrida."""
    paquete = json.loads(RUTA_PAQUETE.read_text(encoding="utf-8"))
    recurso = paquete["resources"][0]
    contenido = RUTA_DATOS.read_bytes()
    recurso["bytes"] = len(contenido)
    recurso["hash"] = f"sha256:{hashlib.sha256(contenido).hexdigest()}"
    recurso["rows"] = len(tabla)

    rangos = {
        columna: {
            "desde": f"{tabla[columna].min():%Y-%m-%d}",
            "hasta": f"{tabla[columna].max():%Y-%m-%d}",
            "filas_con_dato": int(tabla[columna].notna().sum()),
        }
        for columna in COLUMNAS_FECHA
    }
    paquete["updated"] = f"{ahora:%Y-%m-%d}"
    paquete["cobertura"] = {
        "filas": len(tabla),
        "filas_abiertas": int(tabla["fecha_fin"].isna().sum()),
        "filas_por_estado": tabla["estado"].value_counts().sort_index().to_dict(),
        "rangos": rangos,
    }
    temporal = RUTA_PAQUETE.with_suffix(".json.tmp")
    temporal.write_text(
        json.dumps(paquete, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporal, RUTA_PAQUETE)


# --- Cobertura en el readme --------------------------------------------------

MARCA_INICIO = "<!-- cobertura:inicio -->"
MARCA_FIN = "<!-- cobertura:fin -->"
RUTA_README = RUTA_DATOS.with_name("readme.md")
PAUSA_MAXIMA_EPISODIO = pd.Timedelta(hours=24)
MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
    "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]  # fmt: skip
ETIQUETAS_ESTADO = {
    "b": "Transitable con precaución",
    "c": "Transitable con desvíos",
    "d": "No transitable, tráfico cerrado",
    "e": "No transitable por conflictos sociales",
    "g": "Restricción vehicular",
    "h": "Restricción vehicular especial",
    "i": "Obstrucción por trabajos de limpieza",
}


def calcular_episodios(tabla: pd.DataFrame, ahora: datetime) -> pd.DataFrame:
    """Une las filas de conflicto en episodios.

    Un episodio reúne las filas de conflicto de una misma coordenada sin pausas
    de más de 24 horas. Excluye la coordenada (0, 0). Una fila abierta cuenta
    hasta `ahora`. `fin` es nulo si el episodio sigue abierto.
    """
    conflictos = tabla[
        tabla["estado"].str.startswith("e -")
        & ~((tabla["latitud"] == 0) & (tabla["longitud"] == 0))
    ].sort_values([*COLUMNAS_COORDENADA, "fecha_reporte"])
    lugar = [conflictos["latitud"], conflictos["longitud"]]
    fin_efectivo = conflictos["fecha_fin"].fillna(pd.Timestamp(ahora))
    fin_previo = fin_efectivo.groupby(lugar).transform(lambda s: s.cummax().shift())
    inicia = fin_previo.isna() | (
        conflictos["fecha_reporte"] > fin_previo + PAUSA_MAXIMA_EPISODIO
    )
    conflictos["episodio"] = inicia.groupby(lugar).cumsum()
    return (
        conflictos.groupby([*COLUMNAS_COORDENADA, "episodio"])
        .agg(
            inicio=("fecha_reporte", "min"),
            fin=("fecha_fin", lambda s: pd.NaT if s.isna().any() else s.max()),
            filas=("fecha_reporte", "size"),
        )
        .reset_index()
    )


def formato_numero(valor: float, decimales: int = 0) -> str:
    """Formatea con espacio para los miles y coma para los decimales."""
    texto = f"{valor:,.{decimales}f}"
    return texto.replace(",", " ").replace(".", ",")


def formato_fecha(fecha: pd.Timestamp) -> str:
    return f"{fecha.day} de {MESES[fecha.month - 1]} de {fecha.year}"


def tabla_markdown(encabezados: list[str], filas: list[list]) -> str:
    lineas = [
        "| " + " | ".join(encabezados) + " |",
        "|" + "|".join("---" for _ in encabezados) + "|",
    ]
    lineas += ["| " + " | ".join(str(celda) for celda in fila) + " |" for fila in filas]
    return "\n".join(lineas)


def episodios_activos_por_dia(episodios: pd.DataFrame, ahora: datetime) -> pd.Series:
    """Cuenta los episodios activos cada día al mediodía, hasta `ahora`."""
    inicios = episodios["inicio"].sort_values().to_numpy()
    fines = episodios["fin"].fillna(pd.Timestamp(ahora)).sort_values().to_numpy()
    dias = pd.date_range(
        episodios["inicio"].min().normalize() + pd.Timedelta(hours=12),
        pd.Timestamp(ahora).normalize() + pd.Timedelta(hours=12),
        freq="D",
    )
    dias = dias[dias <= pd.Timestamp(ahora)]
    activos = pd.Series(dias, index=dias).map(
        lambda t: int(
            inicios.searchsorted(t.to_datetime64(), side="right")
            - fines.searchsorted(t.to_datetime64(), side="left")
        )
    )
    return activos


def redactar_cobertura(tabla: pd.DataFrame, ahora: datetime) -> str:
    """Redacta en markdown las cifras de cobertura del readme."""
    episodios = calcular_episodios(tabla, ahora)
    fin_efectivo = episodios["fin"].fillna(pd.Timestamp(ahora))
    duracion = (fin_efectivo - episodios["inicio"]).dt.total_seconds() / 86400
    activos = episodios_activos_por_dia(episodios, ahora)
    inicio_serie = tabla["fecha_consulta"].min()
    dias_serie = pd.date_range(
        inicio_serie.normalize(), pd.Timestamp(ahora).normalize()
    )
    por_anio = episodios["inicio"].dt.year.value_counts().sort_index()
    por_mes = episodios["inicio"].dt.to_period("M").value_counts()
    mes_mayor = por_mes.idxmax()
    estados = tabla["estado"].value_counts()
    pico = activos.idxmax()
    es_conflicto = tabla["estado"].str.startswith("e -")

    partes = [
        f"Cifras al {formato_fecha(pd.Timestamp(ahora))}. Se actualizan en cada corrida.",
        tabla_markdown(
            ["Dato", "Valor"],
            [
                ["Inicio de la serie", formato_fecha(inicio_serie)],
                ["Filas", formato_numero(len(tabla))],
            ],
        ),
        "Filas por estado:",
        tabla_markdown(
            ["Estado", "Filas"],
            [
                [ETIQUETAS_ESTADO.get(estado[0], estado), formato_numero(filas)]
                for estado, filas in estados.items()
            ],
        ),
        "Conflictos:",
        tabla_markdown(
            ["Dato", "Valor"],
            [
                ["Filas de conflicto", formato_numero(es_conflicto.sum())],
                ["Episodios de conflicto", formato_numero(len(episodios))],
                [
                    "Días con al menos un episodio activo",
                    f"{formato_numero(100 * (activos > 0).sum() / len(dias_serie))} %",
                ],
                [
                    "Máximo de episodios activos al mismo tiempo",
                    f"{formato_numero(activos.max())} ({formato_fecha(pico)})",
                ],
            ],
        ),
        "Duración de un episodio de conflicto:",
        tabla_markdown(
            ["Medida", "Duración en días"],
            [
                ["Mediana", formato_numero(duracion.median(), 1)],
                ["Percentil 90", formato_numero(duracion.quantile(0.9), 1)],
                ["Máximo", formato_numero(duracion.max(), 1)],
            ],
        ),
        "Episodios de conflicto por año en que empiezan:",
        tabla_markdown(
            ["Año", "Episodios"],
            [[anio, formato_numero(n)] for anio, n in por_anio.items()],
        ),
        (
            f"El año {por_anio.index[0]} cuenta desde {MESES[inicio_serie.month - 1]} "
            f"y el año {por_anio.index[-1]} cuenta hasta el {ahora.day} de "
            f"{MESES[ahora.month - 1]}. El mes con más episodios nuevos es "
            f"{MESES[mes_mayor.month - 1]} de {mes_mayor.year} "
            f"({formato_numero(por_mes.max())})."
        ),
    ]
    return "\n\n".join(partes)


def actualizar_readme(tabla: pd.DataFrame, ahora: datetime) -> None:
    """Reemplaza el texto entre las marcas de cobertura del readme."""
    texto = RUTA_README.read_text(encoding="utf-8")
    inicio = texto.index(MARCA_INICIO) + len(MARCA_INICIO)
    fin = texto.index(MARCA_FIN)
    nuevo = f"{texto[:inicio]}\n\n{redactar_cobertura(tabla, ahora)}\n\n{texto[fin:]}"
    temporal = RUTA_README.with_suffix(".md.tmp")
    temporal.write_text(nuevo, encoding="utf-8")
    os.replace(temporal, RUTA_README)


# --- Programa principal ------------------------------------------------------


def main() -> None:
    if not os.environ.get("GEMINI_API_KEY"):
        raise RuntimeError("Falta la variable de entorno GEMINI_API_KEY")
    # Hora de Bolivia sin zona, como en el resto de la tabla.
    ahora = datetime.now(ZONA_HORARIA).replace(tzinfo=None, microsecond=0)
    print("Consultando eventos vía API ...")
    eventos = descargar_eventos()
    print(f"Eventos vigentes: {len(eventos)}")

    vigentes = dar_formato(
        pd.DataFrame([evento_a_fila(evento, ahora) for evento in eventos])
    )
    tabla = consolidar(leer_historico(), vigentes, ahora)
    guardar(tabla)
    actualizar_metadatos(tabla, ahora)
    try:
        actualizar_readme(tabla, ahora)
    except Exception as error:  # noqa: BLE001
        # Las cifras del readme no deben impedir que se guarden los datos.
        print(f"No pude actualizar las cifras del readme: {error}", file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # noqa: BLE001
        sys.exit(f"No pude actualizar data.csv: {error}")
