> Datos históricos de transitabilidad en carreteras de Bolivia 

La Agencia Boliviana de Caminos mantiene un registro de incidentes en carreteras a nivel nacional del cual podemos acceder a [algunas vistas públicas](http://transitabilidad.abc.gob.bo/mapa). Sin embargo no encuentro una vista histórica que permita observar, por ejemplo, cómo conflictos sociales aparecen y desaparecen en el tiempo. Por eso, en este repositorio archivo estos datos automáticamente cada dos horas. Estos datos podrían ayudar a entender incidentes y los fenómenos que los ocasionan, identificar incidentes que tardan en ser resueltos, o contribuir a investigaciones donde importa la posición geográfica de bloqueos sociales, entre muchos otros usos. 

Para consolidar estos datos creo 2 columnas nuevas:

- `fecha_consulta` indica el momento que consulto la fuente
- `fecha_fin` indica el momento de consulta en que detecto que un incidente ha dejado de ser reportado

Las otras columnas reproducen la información en la fuente y sus nombres sólo han sido mínimamente normalizados para facilitar su manipulación. Todos los tiempos están en zona horaria `GMT -04:00`. 

---

Los datos recolectados entre el 7 y el 15 de agosto de 2020, donde la columna `fecha_fin` no es correcta por un error en el código, pueden ser encontrados [acá](https://github.com/mauforonda/transitabilidad-bolivia/blob/master/update/20200807_20200815.csv). 

