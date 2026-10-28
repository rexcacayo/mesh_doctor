# Mesh Doctor

> **Versión actual: 1.1.0** (Blender 4.2 – 5.x) → instalar `version_1.1.0/dist/mesh_doctor-1.1.0.zip`

Complemento de Blender que **analiza un modelo y lo deja perfecto** antes de imprimirlo, partirlo o separarlo por colores. Es el primer paso del flujo:

**Mesh Doctor → BigPrint / MagSnap → Color Print Splitter → exportar**

## Qué revisa

Tamaño y unidades, vértices duplicados, triángulos rotos, uniones en T (3MF pintados), agujeros, aristas no-manifold, normales, piezas, motas, capas internas, huecos encerrados, piezas del revés, autointersecciones, paredes más finas que la boquilla, colores y número de caras. Semáforo verde / ámbar / rojo.

## Qué arregla con «Dejar perfecto»

Suelda, cose uniones en T, quita triángulos rotos, motas y capas internas, cierra agujeros con un parche suave, orienta las normales, une piezas solapadas y resuelve cruces. Si la malla sigue cruzándose consigo misma, la rehace con vóxeles (detalle automático) y copia los colores. Crea `<modelo>_ok` y deja el original oculto. Los colores (materiales por cara) se conservan.

## Diezmar inteligente (1.1.0)

Quita caras sin perder forma según tu boquilla: diezma por pasos sobre el original, mide la desviación
(Hausdorff con muestreo) y se queda con el último paso que no pasa de 0,03 / 0,05 / 0,1 / 0,15 mm
(boquilla 0,25 / 0,4 / 0,6 / 0,8). Repara después y deja un mapa de calor de dónde se perdió forma.
El análisis avisa cuando una malla tiene más caras de las que tu boquilla y el tamaño de la pieza necesitan.

## Versiones

| Versión | Novedades |
|---|---|
| 1.1.0 | Diezmar inteligente por boquilla y tamaño, con desviación medida y mapa de calor; aviso de malla sobredimensionada en el análisis; selector de tipo de pieza. |
| 1.0.3 | Repara varias piezas seleccionadas, ignora el estudio de Showcase, avisa si no hay caras. |
| 1.0.2 | Rehacer sólido tapa agujeros antes de los vóxeles y no dispara las caras. |
| 1.0.1 | Si la reparación no basta, rehace el sólido con vóxeles automáticamente; quita trocitos sueltos tras rehacer; detalle automático; los huecos encerrados ya no cuentan como «del revés». |
| 1.0.0 | Primera versión. |

## Licencia

GPL-3.0-or-later (ver [LICENSE](LICENSE)). Gratis para usar, modificar y compartir; si redistribuyes una versión modificada, publica también su código. Es la licencia que exige extensions.blender.org.
