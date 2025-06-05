#!/usr/bin/env python3

import requests
from bs4 import BeautifulSoup
import re
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
import sys

def normalize(text:str, key:bool=False):
  if key:
    text = text.replace(':', '').replace(' ', '_')
  return text.lower().strip()

def format_columns(df):
  col = {'dates': ['fecha_reporte', 'fecha_consulta', 'fecha_fin'],
         'category': ['estado', 'evento', 'clima', 'horario_de_corte', 'tipo_de_carretera', 'alternativa_de_circulación_o_desvios', 'restricción_vehicular', 'trabajos_de_conservación_vial'],
         'string': ['sección', 'sector'],
         'float': ['latitud', 'longitud']}
  for field in col['dates']:
    df[field] = pd.to_datetime(df[field].fillna(pd.NaT))
  df[col['category']] = df[col['category']].astype('category')
  df[col['string']] = df[col['string']].astype('string')

  df[col['float']] = df[col['float']].apply(
    lambda _: _.astype(str).str.strip().apply(lambda __: float(__) if __ else np.nan)
  )
  return df

def parse_html():
  data = []
  try:
    html = requests.get(
        'https://transitabilidad.abc.gob.bo/mapa',
        verify=False,
        proxies={'http': 'http://190.181.30.54:5678'},
    ).text
    popups = re.findall(r'\.bindPopup\(\'<img alt\=\"\" src\=.*', html)
    if len(popups) > 0:
      data = []
      for popup in popups:
        if 'youtube' not in popup:
          point = {}
          soup = BeautifulSoup(''.join(popup.split("\' + \'")), 'html.parser')
          fields = soup.select('b[style*="color: #f5b041"]')
          fields.extend(soup.select('b')[-2:])
          for field in fields:
            point[normalize(field.get_text(), key=True)] = normalize(str(field.next_sibling))
          data.append(point)
      df = pd.DataFrame(data)
      df['fecha_consulta'] = now
      df['fecha_consulta'] = df['fecha_consulta'].dt.tz_localize(None)
      df['fecha_fin'] = ''
      df = format_columns(df)
      return df.sort_values(['fecha_reporte', 'sección'])
    else:
      return None
  except requests.exceptions.RequestException as e:
    sys.exit("El mapa está inaccesible")

def consolidate(df):
  # retrieve saved entries
  oldf = pd.read_csv('data.csv', na_filter=False)
  oldf = format_columns(oldf)

  # compare entries and filter duplicates
  compare_cols = [
    'fecha_reporte',
    'estado',
    'sección',
    'evento',
    'clima',
    'horario_de_corte',
    'tipo_de_carretera',
    'alternativa_de_circulación_o_desvios',
    'restricción_vehicular',
    'sector',
    'trabajos_de_conservación_vial'
  ]
  joindf = pd.concat([oldf, df], axis=0, ignore_index=True)
  duplicates = joindf[joindf.duplicated(subset=compare_cols, keep='last')]

  # get entries that are not present in the newly fetched data
  expired = pd.concat([oldf, duplicates], axis=0, ignore_index=True)
  expired = expired[~expired.duplicated(subset=compare_cols, keep=False)]
  expired.loc[expired['fecha_fin'].isna(), ['fecha_fin']] = now.replace(tzinfo=None)

  # get new entries
  new = pd.concat([df, duplicates], axis=0, ignore_index=True)
  new = new[~new.duplicated(subset=compare_cols, keep=False)]

  # join expired, duplicates and new entries

  finaldf = pd.concat([expired, duplicates, new], axis=0, ignore_index=True).sort_values(['fecha_reporte', 'sección'])
  return format_columns(finaldf)

now = datetime.now(timezone(timedelta(hours=-4)))
df = parse_html()
if df is not None:
  consolidate(df).to_csv('data.csv', index=False, date_format='%Y-%m-%d %H:%M:%S', float_format='%.5f', columns=['fecha_consulta', 'fecha_reporte', 'fecha_fin', 'latitud', 'longitud', 'estado', 'sección', 'evento', 'clima', 'horario_de_corte', 'tipo_de_carretera', 'alternativa_de_circulación_o_desvios', 'restricción_vehicular', 'sector', 'trabajos_de_conservación_vial'])
