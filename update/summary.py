#!/usr/bin/env python3

import pandas as pd
import datetime as dt
import json

# events that indicate social conflicts in the source classification
conflict_events = ['e - no transitable por conflictos sociales']

def at_noon(date):
    "sets a date at noon"
    return dt.datetime(date.year, date.month, date.day, 12, 0, 0)

def active_conflicts_in_day(data, day):
    "returns the number of active conflict and non-conflict events in a day"
    
    ended = (data[(data.fecha_reporte < day) & (data.fecha_fin > day)]
            .conflicto
            .value_counts())
    ongoing = data[(data.fecha_reporte < day) & (data.fecha_fin.isna())]
    if ongoing.shape[0] > 0:
        return (pd.concat([ended, ongoing.conflicto.value_counts()], axis=1)
                .sum(axis=1)
                .to_dict())
    else:
        return ended.to_dict()

def load_and_prepare_data():
    "loads data and creates a column to classify events as conflicts"
    df = pd.read_csv(
        'data.csv',
        parse_dates=['fecha_consulta', 'fecha_reporte', 'fecha_fin'])
    df['conflicto'] = df.estado.isin(conflict_events).map({False:'no_conflicto', True:'conflicto'})
    return df

def list_everyday(data):
    "returns a list of every day covered by the dataset at noon"
    return pd.date_range(
        at_noon(data.fecha_reporte.min()),
        at_noon(data.fecha_reporte.max()),
        freq='D')

def conflicts_everyday(data):
    "creates a dataframe with the number of conflict and non-conflict events for every day covered by the dataset"
    everyday = list_everyday(data)
    return (
        pd.DataFrame(
            [{**{'fecha':day}, **active_conflicts_in_day(data, day)} for day in everyday])
        .fillna(0)
        .set_index('fecha')
        .astype(int))

def active_conflicts_now(data):
    with open('activos_ahora.json', 'w+') as f:
        json.dump(data[data.fecha_fin.isna()].conflicto.value_counts().to_dict(), f)

data = load_and_prepare_data()
conflict_timeline = conflicts_everyday(data)
conflict_timeline.to_csv('activos_diarios.csv', date_format='%Y-%m-%d')
active_conflicts_now(data)
