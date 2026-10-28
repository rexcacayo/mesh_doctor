# Mesh Doctor 1.1.0

Complemento clásico para Blender 4.2 a 5.x (probado en 5.2.1 LTS). Sin dependencias externas.

El primer paso de todo: coge cualquier modelo (IA, escaneo, 3MF pintado, STL de internet) y déjalo perfecto antes de BigPrint, MagSnap o Color Splitter.

## Uso (pestaña Mesh Doctor)

1. Selecciona el modelo, elige tu boquilla y pulsa **Analizar**. Semáforo y lista: tamaño/unidades, vértices duplicados, triángulos rotos, uniones en T, agujeros, aristas no-manifold, normales, piezas, motas, capas internas, piezas del revés, autointersecciones, paredes finas, colores y caras.
2. **Dejar perfecto**: suelda, cose uniones en T, quita triángulos rotos, motas y capas internas, cierra agujeros con un parche suave, orienta las normales, une piezas solapadas (opcional: reduce caras). Crea `<modelo>_ok` y oculta el original. Los colores se conservan.
3. Si sigue en rojo (la malla se cruza consigo misma), **Rescate → Rehacer sólido**: lo rehace con vóxeles (siempre cerrado) y copia los colores.
4. **Diezmar inteligente**: quita caras sin perder forma. Elige arriba la boquilla y el tipo de pieza
   (orgánico con detalle, orgánico liso o mecánico) y pulsa el botón. Crea `<modelo>_diezmado` y oculta el original.
   Debajo verás el antes y el después (caras, desviación máxima y media) y **Ver mapa de desviación**
   pinta la pieza: verde = no ha cambiado, rojo = en el límite de tu boquilla.

## Qué cambia en 1.1.0

- **Diezmar inteligente**: más caras no es más detalle; una malla de IA de 300.000 caras puede dar errores
  de impresión (micro-segmentos en el G-code) y a 150.000 salir perfecta. Diezma **por pasos, siempre sobre
  el original**, mide la desviación contra el original (Hausdorff con 20.000 puntos en cada sentido) y se
  queda con el último paso que no pasa de la desviación de tu boquilla:
  0,25 → 0,03 mm · 0,4 → 0,05 mm · 0,6 → 0,1 mm · 0,8 → 0,15 mm.
  Después repara (suelda, normales, cierra si se abrió) y deja el **mapa de calor** de dónde se perdió forma.
- **Análisis**: las caras ya no se juzgan con un tope fijo. Según la boquilla, el tipo de pieza y el tamaño
  (sale de la superficie total, no de la altura) avisa «Malla sobredimensionada: bastan 150k–400k caras».
- Selector **Tipo de pieza** junto a la boquilla (lo usan el análisis y el diezmado).

| Caras orientativas (orgánico) | 0,25 | 0,4 | 0,6 | 0,8 |
|---|---|---|---|---|
| Pequeña (≤ 50 mm) | 150k–300k | 50k–150k | 30k–80k | 20k–50k |
| Media (50–150 mm) | 300k–600k | 150k–400k | 80k–200k | 50k–120k |
| Grande (> 150 mm) | 500k–1M | 300k–800k | 150k–400k | 100k–250k |

Orgánico con detalle: todo el rango · orgánico liso: de 0,6 × el mínimo a la mitad del rango · mecánico:
5k–20k. Es solo orientativo: lo que manda es la desviación, y el mínimo del rango es el suelo de seguridad.

## Qué cambió en 1.0.3

- **Dejar perfecto con varias piezas seleccionadas** las repara todas, una a una (antes solo la activa).
- El suelo, las luces y la cámara del estudio de **Showcase** ya no se cogen como modelo por error.
- Si una malla no tiene caras útiles, avisa con un mensaje claro en vez de dar un error de Python.

## Qué cambió en 1.0.2

- **Rehacer sólido** ya funciona con mallas con agujeros: antes la pieza principal podía perderse entera
  (los vóxeles no sabían qué era «dentro»). Ahora tapa los agujeros antes de rehacer.
- **Rehacer sólido** y **Dejar perfecto** (cuando tiene que rehacer el sólido) ya no multiplican las caras (antes un modelo de
  260.000 caras salía con 1,5 millones): como mucho el doble del original (mínimo 300.000).

## Límites

- Las autointersecciones solo se miden en modelos de menos de 600.000 caras.
- Los parches de agujeros grandes quedan suaves pero no inventan detalle: para reconstruir zonas que faltan, 3D LAB.
