# Transitabilidad en carreteras de Bolivia

Este repositorio guarda el histórico de los eventos de transitabilidad que publica la [Agencia Boliviana de Caminos (ABC)](https://transitabilidad.abc.gob.bo). Una [GitHub Action](.github/workflows/actualizar.yml) consulta la fuente cada dos horas y agrega los cambios a una sola tabla, [`data.csv`](data.csv). El archivo [`datapackage.json`](datapackage.json) describe cada campo y las precauciones de uso.

## Qué es

### Qué publica la ABC y cómo interpretarlo

La ABC publica la lista de eventos que afectan hoy el tránsito en las carreteras del país. Cada evento tiene un estado (por ejemplo, "transitable con desvíos" o "no transitable por conflictos sociales"), el tramo afectado, la coordenada donde empieza el tramo, una causa y la hora en que la ABC lo registró. La fuente no ofrece una vista histórica de los eventos que terminan. Esta tabla sí los conserva. Cada vez que consulta la fuente, agrega los eventos nuevos y anota la hora en que un evento deja de aparecer.

Cada fila de la tabla es un evento tal como lo registró la ABC. Una fila no equivale a un bloqueo. Cuando un bloqueo dura varios días, la ABC lo vuelve a registrar varias veces y cada registro produce una fila nueva. Para estudiar bloqueos hay que unir esas filas.

En este readme, un **conflicto** es un evento con el estado "no transitable por conflictos sociales". Un **episodio de conflicto** es un grupo de filas de conflicto en la misma coordenada, sin pausas de más de 24 horas entre una fila y la siguiente. Un episodio es la mejor aproximación disponible a un bloqueo. No es un identificador oficial y la regla de 24 horas es una convención.

### Cobertura

<!-- cobertura:inicio -->

Cifras al 25 de noviembre de 2026. Se actualizan en cada corrida.

| Dato | Valor |
|---|---|
| Inicio de la serie | 15 de agosto de 2020 |
| Filas | 42 886 |

Filas por estado:

| Estado | Filas |
|---|---|
| Transitable con desvíos | 12 392 |
| No transitable por conflictos sociales | 11 084 |
| Transitable con precaución | 9 303 |
| Restricción vehicular | 5 797 |
| No transitable, tráfico cerrado | 2 646 |
| Restricción vehicular especial | 1 500 |
| Obstrucción por trabajos de limpieza | 164 |

Conflictos:

| Dato | Valor |
|---|---|
| Filas de conflicto | 11 084 |
| Episodios de conflicto | 2 600 |
| Días con al menos un episodio activo | 53 % |
| Máximo de episodios activos al mismo tiempo | 97 (1 de agosto de 2024) |

Duración de un episodio de conflicto:

| Medida | Duración en días |
|---|---|
| Mediana | 1,0 |
| Percentil 90 | 6,6 |
| Máximo | 46,2 |

Episodios de conflicto por año en que empiezan:

| Año | Episodios |
|---|---|
| 2020 | 86 |
| 2021 | 377 |
| 2022 | 436 |
| 2023 | 457 |
| 2024 | 469 |
| 2025 | 262 |
| 2026 | 513 |

El año 2020 cuenta desde agosto y el año 2026 cuenta hasta el 25 de noviembre. El mes con más episodios nuevos es mayo de 2026 (252).

<!-- cobertura:fin -->

### Preguntas que la tabla ayuda a responder

- ¿Cuántos bloqueos había activos cada día y cómo cambia ese número entre meses y años?
- ¿Cuánto dura un bloqueo y qué tramos se bloquean con más frecuencia o por más tiempo?
- ¿Cuándo empieza y cuándo termina una ola de bloqueos, como la de mayo y junio de 2026?
- ¿Qué parte de los cierres de carretera se atribuye a conflictos y qué parte a derrumbes, obras o restricciones?
- ¿Dónde coinciden varios bloqueos al mismo tiempo y qué corredores quedan sin alternativa de circulación?

## Cómo usarlo

Lea primero [`datapackage.json`](datapackage.json). Describe cada campo, trae las advertencias completas (`advertencias`) y reúne las mismas consultas de abajo (`ejemplos`). Consulte la tabla con DuckDB desde la carpeta donde está `data.csv`. Las consultas de abajo están completas y funcionan tal como están. Las que usan la vista `episodios` suponen que ya la creó en la misma sesión.

```sql
SELECT * FROM 'data.csv' LIMIT 5;
```

Elija la recomendación que corresponde a su pregunta.

### Si necesita identificar conflictos

Filtre con `estado LIKE 'e -%'`. El campo `evento` describe la causa y a veces contradice el estado. Esta guía usa el estado. La primera consulta cuenta las filas según las dos definiciones. La segunda muestra las causas registradas dentro del estado de conflicto. Algunas no son sociales, como accidentes o caída de rocas. Indique en su análisis qué definición usó.

```sql
SELECT
    estado LIKE 'e -%' AS estado_conflicto,
    evento LIKE 'bloqueo%' AS evento_bloqueo,
    count(*) AS filas
FROM 'data.csv'
GROUP BY ALL
ORDER BY ALL;
```

```sql
SELECT evento, count(*) AS filas
FROM 'data.csv'
WHERE estado LIKE 'e -%'
GROUP BY evento
ORDER BY filas DESC
LIMIT 10;
```

### Si necesita contar bloqueos

No cuente filas. Cree la vista `episodios`, que tiene una fila por episodio de conflicto con las columnas `latitud`, `longitud`, `inicio`, `fin` (nulo si el episodio sigue abierto) y `filas`. La vista excluye la coordenada (0, 0). Una variante de la regla que une filas a menos de 500 metros da casi el mismo número de episodios.

```sql
CREATE OR REPLACE VIEW episodios AS
WITH ultima AS (
    SELECT max(fecha_consulta) AS t FROM 'data.csv'
),
conflictos AS (
    SELECT
        d.*,
        max(coalesce(d.fecha_fin, ultima.t)) OVER (
            PARTITION BY d.latitud, d.longitud
            ORDER BY d.fecha_reporte
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
        ) AS fin_previo
    FROM 'data.csv' d CROSS JOIN ultima
    WHERE d.estado LIKE 'e -%' AND NOT (d.latitud = 0 AND d.longitud = 0)
),
marcadas AS (
    SELECT
        *,
        sum((fin_previo IS NULL OR fecha_reporte > fin_previo + INTERVAL 24 HOUR)::INT) OVER (
            PARTITION BY latitud, longitud ORDER BY fecha_reporte
        ) AS episodio
    FROM conflictos
)
SELECT
    latitud,
    longitud,
    episodio,
    min(fecha_reporte) AS inicio,
    CASE WHEN bool_or(fecha_fin IS NULL) THEN NULL ELSE max(fecha_fin) END AS fin,
    count(*) AS filas
FROM marcadas
GROUP BY latitud, longitud, episodio;
```

Episodios por año de inicio:

```sql
SELECT year(inicio) AS anio, count(*) AS episodios
FROM episodios
GROUP BY anio
ORDER BY anio;
```

Episodios activos cada día al mediodía, en este caso para mayo y junio de 2026:

```sql
SELECT d::DATE AS dia, count(*) AS episodios_activos
FROM generate_series(TIMESTAMP '2026-05-01 12:00', TIMESTAMP '2026-06-30 12:00', INTERVAL 1 DAY) AS g(d)
JOIN episodios e ON e.inicio <= d AND (e.fin IS NULL OR e.fin >= d)
GROUP BY dia
ORDER BY dia;
```

### Si necesita medir cuánto dura un bloqueo

Mida la duración del episodio y no la de una fila. `fecha_fin` es la primera consulta en que el evento ya no aparece, así que es algo posterior al fin real. Cuando `fin` es nulo, el episodio sigue abierto. La consulta usa entonces la hora de la última consulta como fin provisional.

```sql
SELECT
    round(median(dias), 1) AS mediana,
    round(quantile_cont(dias, 0.9), 1) AS percentil_90,
    round(max(dias), 1) AS maximo
FROM (
    SELECT epoch(coalesce(fin, (SELECT max(fecha_consulta) FROM 'data.csv')) - inicio) / 86400 AS dias
    FROM episodios
);
```

### Si necesita saber cuándo empezó un bloqueo

Use la columna `inicio` de la vista `episodios`. No use la `fecha_reporte` de una fila cualquiera, porque es la hora del último registro y no la hora de inicio. Gran parte de las filas de conflicto tiene hora 06, probablemente porque la ABC vuelve a registrar los eventos activos a esa hora. Por eso, no describa patrones por hora del día ni por día de la semana con `fecha_reporte`.

```sql
SELECT inicio::DATE AS dia, count(*) AS episodios_nuevos
FROM episodios
WHERE inicio >= '2026-05-01' AND inicio < '2026-07-01'
GROUP BY dia
ORDER BY dia;
```

### Si necesita agrupar o dibujar por lugar

La vista `episodios` ya excluye las filas con coordenadas inválidas. Si trabaja con la tabla completa, excluya las filas con latitud 0 y longitud 0, porque mezclan lugares distintos y caen en el océano Atlántico. También hay filas con longitud positiva, que son un error de signo. Esta consulta cuenta ambos casos.

```sql
SELECT
    count(*) FILTER (WHERE latitud = 0 AND longitud = 0) AS coordenada_cero,
    count(*) FILTER (WHERE longitud > 0) AS longitud_positiva
FROM 'data.csv';
```

La coordenada marca el inicio del tramo y no el sitio exacto del bloqueo. Dos coordenadas distintas no siempre son dos lugares distintos, porque algunas están a menos de 100 metros. El campo `sección` tampoco identifica un lugar: el mismo tramo aparece con varias coordenadas, y algunas filas tienen el carácter `?` en lugar de una letra acentuada. Para agrupar por zona, redondee las coordenadas. Esta consulta cuenta los episodios por zona de unos 1 000 metros.

```sql
SELECT round(latitud, 2) AS latitud, round(longitud, 2) AS longitud, count(*) AS episodios
FROM episodios
GROUP BY ALL
ORDER BY episodios DESC
LIMIT 10;
```

### Si necesita comparar años

Compare episodios y no filas. El número de filas de conflicto creció mucho en 2026, pero el número de episodios no creció en la misma proporción.

```sql
WITH f AS (
    SELECT year(fecha_reporte) AS anio, count(*) AS filas
    FROM 'data.csv'
    WHERE estado LIKE 'e -%' AND NOT (latitud = 0 AND longitud = 0)
    GROUP BY anio
),
e AS (
    SELECT year(inicio) AS anio, count(*) AS episodios
    FROM episodios
    GROUP BY anio
)
SELECT * FROM f JOIN e USING (anio) ORDER BY anio;
```

### Si necesita interpretar un periodo sin conflictos

La tabla no registra las corridas fallidas. Un periodo sin cambios y una interrupción de la recolección se ven igual. La primera consulta muestra que julio de 2026 tiene eventos nuevos casi todos los días y ninguna fila de conflicto. Ese mes es un periodo sin conflictos y no una interrupción. La segunda consulta lista los intervalos más largos sin ningún cambio. Esos intervalos pueden ser interrupciones o periodos tranquilos.

```sql
SELECT
    strftime(fecha_consulta, '%Y-%m') AS mes,
    count(DISTINCT fecha_consulta::DATE) AS dias_con_eventos_nuevos,
    count(*) FILTER (WHERE estado LIKE 'e -%') AS filas_de_conflicto
FROM 'data.csv'
WHERE fecha_consulta >= '2026-06-01'
GROUP BY mes
ORDER BY mes;
```

```sql
WITH cambios AS (
    SELECT DISTINCT fecha_consulta AS t FROM 'data.csv'
    UNION
    SELECT fecha_fin FROM 'data.csv' WHERE fecha_fin IS NOT NULL
),
intervalos AS (
    SELECT lag(t) OVER (ORDER BY t) AS desde, t AS hasta FROM cambios
)
SELECT desde, hasta, hasta - desde AS duracion
FROM intervalos
WHERE hasta - desde > INTERVAL 24 HOUR
ORDER BY duracion DESC
LIMIT 5;
```

### Si necesita agrupar por tipo de carretera, clima o restricción vehicular

Normalice el texto antes de agrupar. La ABC cambió la redacción con el tiempo, así que `asfaltada` y `carretera asfaltada` significan lo mismo. Las mismas diferencias afectan a `clima` y a `restricción_vehicular`.

```sql
SELECT replace(tipo_de_carretera, 'carretera ', '') AS tipo_de_carretera, count(*) AS filas
FROM 'data.csv'
GROUP BY ALL
ORDER BY filas DESC;
```

```sql
SELECT regexp_replace(restricción_vehicular, ', todo tipo de vehiculos$', '') AS restriccion_vehicular, count(*) AS filas
FROM 'data.csv'
GROUP BY ALL
ORDER BY filas DESC
LIMIT 8;
```

### Si necesita trabajar con fechas

Todas las fechas están en hora de Bolivia (GMT-4) y no indican la zona. No las trate como UTC. Esta consulta las convierte a UTC.

```sql
SELECT
    fecha_reporte AS hora_de_bolivia,
    (fecha_reporte AT TIME ZONE 'America/La_Paz') AT TIME ZONE 'UTC' AS hora_utc
FROM 'data.csv'
LIMIT 3;
```

### Si necesita generalizar los resultados

La tabla muestra lo que la ABC publica y cuándo lo publica. No incluye los conflictos que no bloquean carreteras, y no se conoce cuántos bloqueos la ABC no registró.

## Cómo actualizarlo

El workflow [`actualizar.yml`](.github/workflows/actualizar.yml) actualiza la tabla cada dos horas. Para actualizarla a mano:

1. Instale las dependencias con Python 3.13.

   ```bash
   pip install -r requirements.txt
   ```

2. Defina la clave de la API de Gemini. El script la usa para leer el captcha de la fuente.

   ```bash
   export GEMINI_API_KEY=...
   ```

3. Ejecute el script.

   ```bash
   python actualizar.py
   ```

El script resuelve el captcha y descarga los eventos activos. Después los compara con `data.csv`. Agrega los eventos nuevos, mantiene los que siguen activos y escribe `fecha_fin` en los que ya no aparecen. Un evento se identifica con `fecha_reporte`, `latitud` y `longitud`. El script también actualiza `updated` y `cobertura` en `datapackage.json`, y reescribe las cifras de la sección Cobertura de este readme entre las marcas `<!-- cobertura:inicio -->` y `<!-- cobertura:fin -->`. Si falla, no modifica ningún archivo.

El certificado TLS de la fuente venció el 15 de noviembre de 2026. Mientras la ABC no lo renueve, el script no verifica el certificado. Para volver a verificarlo, cambie `VERIFICAR_TLS` a `True` en `actualizar.py`.

Para que el workflow funcione, agregue el secreto `GEMINI_API_KEY` en la configuración del repositorio.

Los datos del 7 al 15 de agosto de 2020 tienen una `fecha_fin` incorrecta por un error de código. Están en [el historial de git](https://github.com/mauforonda/transitabilidad-bolivia/blob/be4ede4baf0301c87395b3716d29eabbe9f334ce/update/20200807_20200815.csv).
