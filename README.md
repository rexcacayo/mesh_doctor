# Mesh Doctor

> **Versión actual: 1.0.1** (Blender 4.2 – 5.x) → instalar `version_1.0.1/dist/mesh_doctor-1.0.1.zip`

Complemento de Blender que **analiza un modelo y lo deja perfecto** antes de imprimirlo, partirlo o separarlo por colores. Es el primer paso del flujo:

**Mesh Doctor → BigPrint / MagSnap → Color Print Splitter → exportar**

## Qué revisa

Tamaño y unidades, vértices duplicados, triángulos rotos, uniones en T (3MF pintados), agujeros, aristas no-manifold, normales, piezas, motas, capas internas, huecos encerrados, piezas del revés, autointersecciones, paredes más finas que la boquilla, colores y número de caras. Semáforo verde / ámbar / rojo.

## Qué arregla con «Dejar perfecto»

Suelda, cose uniones en T, quita triángulos rotos, motas y capas internas, cierra agujeros con un parche suave, orienta las normales, une piezas solapadas y resuelve cruces. Si la malla sigue cruzándose consigo misma, la rehace con vóxeles (detalle automático) y copia los colores. Crea `<modelo>_ok` y deja el original oculto. Los colores (materiales por cara) se conservan.

## Versiones

| Versión | Novedades |
|---|---|
| 1.0.1 | Si la reparación no basta, rehace el sólido con vóxeles automáticamente; quita trocitos sueltos tras rehacer; detalle automático; los huecos encerrados ya no cuentan como «del revés». |
| 1.0.0 | Primera versión. |
