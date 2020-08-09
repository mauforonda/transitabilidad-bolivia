> Datos históricos de transitabilidad en carreteras de Bolivia 

La Agencia Boliviana de Caminos mantiene un registro de incidentes en carreteras a nivel nacional, del cual podemos acceder a [algunas vistas públicas](http://transitabilidad.abc.gob.bo/mapa). Sin embargo no pude encontrar una vista histórica de estos incidentes, que permita observar, por ejemplo, cómo conflictos sociales emergen y desaparecen en el tiempo. Ese es el objetivo de este repositorio, consulto la fuente de manera automática cada día a medio día y media noche, y guardo los nuevos incidentes que se hayan registrado. 

Para consolidar estos datos, creo 2 columnas nuevas:
- `fecha_consulta` indica el momento que he consultado la fuente
- `fecha_fin` indica el momento de consulta en que he detectado que un incidente ha dejado de ser reportado

Todos las demás columnas reflejan la información provista por la fuente y sus nombres sólo han sido mínimamente normalizados para facilitar su manipulación. Si bien no he encontrado documentación oficial que comunique qué deberíamos leer en estos datos, los valores obtenidos parecen autoexplicativos. Todas los tiempos están en timezone `GMT -04:00`
