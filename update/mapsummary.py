#!/usr/bin/env python

import pandas as pd
import datetime as dt
import json
import pytz

# zona horaria en Bolivia
bolivia = pytz.timezone("America/La_Paz")

# leer datos
date_cols = ['fecha_consulta', 'fecha_reporte', 'fecha_fin']
df = pd.read_csv(
    'data.csv', 
    parse_dates=date_cols
    )
# filtrar conflictos
df = df[df.estado.str.contains('conflictos')]
# agregar un identificador a cada conflicto
df['id'] = 1
df.id = df.id.cumsum()
for col in date_cols:
    df[col] = df[col].dt.tz_localize(bolivia)

# construir la serie de tiempos

timeseries = []

# cada 6 horas entre el primer día de registro y ahora
now = dt.datetime.now(tz=bolivia)
times = pd.date_range(
    start=df.fecha_reporte.min(), 
    end=now, 
    freq='6H',
    tz=bolivia
)

# cada 6 horas qué conflictos están abiertos
for time in times:
    open_conflicts = df[(df.fecha_reporte <= time) & (time <= df.fecha_fin)]['id'].tolist()
    timeseries.append({
        'time': time.isoformat(),
        'open': open_conflicts
    })

# guardar la lista de conflictos para cada tiempo
with open('conflictos_tiempo.json', 'w+') as f:
    json.dump(timeseries, f, indent=2)

# guardar coordenadas para cada conflicto
df[['id', 'latitud', 'longitud']].to_csv('conflictos_coordenadas.csv', index=False)