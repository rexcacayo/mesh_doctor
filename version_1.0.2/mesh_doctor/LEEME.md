# Mesh Doctor 1.0.2

Complemento clásico para Blender 4.2 a 5.x (probado en 5.2.1 LTS). Sin dependencias externas.

El primer paso de todo: coge cualquier modelo (IA, escaneo, 3MF pintado, STL de internet) y déjalo perfecto antes de BigPrint, MagSnap o Color Splitter.

## Uso (pestaña Mesh Doctor)

1. Selecciona el modelo, elige tu boquilla y pulsa **Analizar**. Semáforo y lista: tamaño/unidades, vértices duplicados, triángulos rotos, uniones en T, agujeros, aristas no-manifold, normales, piezas, motas, capas internas, piezas del revés, autointersecciones, paredes finas, colores y caras.
2. **Dejar perfecto**: suelda, cose uniones en T, quita triángulos rotos, motas y capas internas, cierra agujeros con un parche suave, orienta las normales, une piezas solapadas (opcional: reduce caras). Crea `<modelo>_ok` y oculta el original. Los colores se conservan.
3. Si sigue en rojo (la malla se cruza consigo misma), **Rescate → Rehacer sólido**: lo rehace con vóxeles (siempre cerrado) y copia los colores.

## Qué cambia en 1.0.2

- **Rehacer sólido** ya funciona con mallas con agujeros: antes la pieza principal podía perderse entera
  (los vóxeles no sabían qué era «dentro»). Ahora tapa los agujeros antes de rehacer.
- **Rehacer sólido** y **Dejar perfecto** (cuando tiene que rehacer el sólido) ya no multiplican las caras (antes un modelo de
  260.000 caras salía con 1,5 millones): como mucho el doble del original (mínimo 300.000).

## Límites

- Las autointersecciones solo se miden en modelos de menos de 600.000 caras.
- Los parches de agujeros grandes quedan suaves pero no inventan detalle: para reconstruir zonas que faltan, 3D LAB.
