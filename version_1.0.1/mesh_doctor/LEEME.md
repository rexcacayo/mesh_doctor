# Mesh Doctor 1.0.0

Complemento clásico para Blender 4.2 a 5.x (probado en 5.2.1 LTS). Sin dependencias externas.

El primer paso de todo: coge cualquier modelo (IA, escaneo, 3MF pintado, STL de internet) y déjalo perfecto antes de BigPrint, MagSnap o Color Splitter.

## Uso (pestaña Mesh Doctor)

1. Selecciona el modelo, elige tu boquilla y pulsa **Analizar**. Semáforo y lista: tamaño/unidades, vértices duplicados, triángulos rotos, uniones en T, agujeros, aristas no-manifold, normales, piezas, motas, capas internas, piezas del revés, autointersecciones, paredes finas, colores y caras.
2. **Dejar perfecto**: suelda, cose uniones en T, quita triángulos rotos, motas y capas internas, cierra agujeros con un parche suave, orienta las normales, une piezas solapadas (opcional: reduce caras). Crea `<modelo>_ok` y oculta el original. Los colores se conservan.
3. Si sigue en rojo (la malla se cruza consigo misma), **Rescate → Rehacer sólido**: lo rehace con vóxeles (siempre cerrado) y copia los colores.

## Límites

- Las autointersecciones solo se miden en modelos de menos de 600.000 caras.
- Los parches de agujeros grandes quedan suaves pero no inventan detalle: para reconstruir zonas que faltan, 3D LAB.
