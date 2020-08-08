#!/usr/bin/env python3

import requests
from bs4 import BeautifulSoup
import re
import pandas as pd
from datetime import datetime

def normalize(text:str, key:bool=False):
  if key:
    text = text.replace(':', '').replace(' ', '_')
  return text.lower().strip()

def timestamp(df):
  df['fecha_consulta'] = datetime.now()
  df['fecha_consulta'] = df['fecha_consulta'].dt.tz_localize('UTC').dt.tz_convert('America/La_Paz')
  return df

def format_columns(df):
  col = {'dates': 'fecha_reporte',
         'category': ['estado', 'evento', 'clima', 'horario_de_corte', 'tipo_de_carretera', 'alternativa_de_circulación_o_desvios', 'restricción_vehicular', 'trabajos_de_conservación_vial'],
         'string': ['sección', 'sector'],
         'float': ['latitud', 'longitud']}
  df[col['dates']] = pd.to_datetime(df[col['dates']])
  df[col['category']] = df[col['category']].astype('category')
  df[col['string']] = df[col['string']].astype('string')
  df[col['float']] = df[col['float']].astype('float')
  return df

def parse_html():
  data = []
  html = requests.get('http://transitabilidad.abc.gob.bo/movil').text
  for popup in re.findall('\.bindPopup\(\'(<div style="font-size: 10px">.*)\'\)', html):
    point = {}
    soup = BeautifulSoup(''.join(popup.split("\' + \'")), 'html.parser')
    fields = soup.select('b[style*="color: #f5b041"]')
    fields.extend(soup.select('b')[-2:])
    for field in fields:
      point[normalize(field.get_text(), key=True)] = normalize(str(field.next_sibling))
    data.append(point)
    df = format_columns(pd.DataFrame(data))
    df = timestamp(df)
  return df.sort_values('fecha_reporte')

def deduplicate(df):
  oldf = pd.read_csv('data.csv', na_filter=False)
  oldf = format_columns(oldf)
  joindf = pd.concat([oldf, df], axis=0, ignore_index=True)
  joindf = joindf.drop_duplicates(subset=['fecha_reporte', 'estado', 'sección', 'evento', 'clima',      'horario_de_corte', 'tipo_de_carretera', 'alternativa_de_circulación_o_desvios', 'restricción_vehicular',       'sector', 'trabajos_de_conservación_vial'])
  return joindf.sort_values('fecha_reporte')

df = parse_html()
deduplicate(df).to_csv('data.csv', index=False, columns=['fecha_consulta', 'fecha_reporte', 'latitud', 'longitud', 'estado', 'sección', 'evento', 'clima', 'horario_de_corte', 'tipo_de_carretera', 'alternativa_de_circulación_o_desvios', 'restricción_vehicular', 'sector', 'trabajos_de_conservación_vial'])
