# SPDX-FileCopyrightText: 2026 Ricardo Lugaresi
# SPDX-License-Identifier: GPL-3.0-or-later

"""Diezmar inteligente: quitar caras sin perder forma, según la boquilla y el tamaño impreso.

Más caras no es más detalle: lo que cuenta es que los triángulos no sean más pequeños de lo que la
boquilla puede reproducir. Por encima solo hay peso, laminado lento y micro-segmentos en el G-code
(una malla de 300.000 caras dio error a mitad de impresión y a 150.000 salió perfecta).

La regla que manda es la DESVIACIÓN MÁXIMA respecto al original:
    boquilla 0,25 → 0,03 mm · 0,4 → 0,05 mm · 0,6 → 0,1 mm · 0,8 → 0,15 mm
Las caras objetivo de la tabla (por boquilla y tamaño) solo orientan y ponen un suelo de seguridad.

Método: diezmar por pasos SIEMPRE sobre el original → medir la desviación (Hausdorff con muestreo de
puntos en las dos direcciones) → quedarse con el último paso que cumple → reparar (soldar, normales,
cerrar si se abrió) → mapa de calor de dónde se ha perdido forma.
"""
import math
import time

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from . import common
from . import doctor
from . import meshops as mo

DEVIATION = {0.25: 0.03, 0.4: 0.05, 0.6: 0.10, 0.8: 0.15}          # mm

# caras objetivo orientativas (piezas orgánicas o con curvas): pequeña ≤50 · media 50–150 · grande >150 mm
FACES = {
    0.25: ((150_000, 300_000), (300_000, 600_000), (500_000, 1_000_000)),
    0.4: ((50_000, 150_000), (150_000, 400_000), (300_000, 800_000)),
    0.6: ((30_000, 80_000), (80_000, 200_000), (150_000, 400_000)),
    0.8: ((20_000, 50_000), (50_000, 120_000), (100_000, 250_000)),
}
SIZES = ('pequeña', 'media', 'grande')
KIND_ITEMS = [('DETAIL', 'Orgánico con detalle', 'Pelo, escamas, caras: arriba del rango'),
              ('SMOOTH', 'Orgánico liso', 'Formas suaves: en medio o abajo del rango'),
              ('MECH', 'Mecánico / plano', 'Piezas técnicas: muy por debajo (5.000–20.000 suele bastar)')]
KIND_NAMES = {k: n for k, n, _d in KIND_ITEMS}
STEPS = (0.7, 0.5, 0.35, 0.25, 0.18, 0.12, 0.08, 0.055, 0.04, 0.028, 0.02, 0.014, 0.01)
SAMPLES = 20_000
HEAT_ATTR = 'Desviacion'


def nozzle_key(nozzle):
    return min(DEVIATION, key=lambda k: abs(k - float(nozzle)))


def es(x, nd=2):
    return f'{float(x):.{nd}f}'.replace('.', ',')


def fmt_k(n):
    n = float(n)
    if n >= 1_000_000:
        return ('%.1fM' % (n / 1e6)).replace('.0M', 'M').replace('.', ',')
    return '%dk' % round(n / 1000) if n >= 1000 else str(int(n))


# --------------------------------------------------------------------------- tamaño y caras objetivo
def surface_area(V, F):
    return float((np.linalg.norm(np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]]), axis=1) / 2).sum())


def size_class(area, dims):
    """El tamaño lo da la superficie total: lado del cubo con la misma superficie. La caja de
    medidas solo se enseña como referencia (una pieza alargada engaña por la altura)."""
    side = math.sqrt(max(area, 0.0) / 6.0)
    idx = 0 if side <= 50 else 1 if side <= 150 else 2
    return idx, side


def face_target(nozzle, area, dims, kind='SMOOTH'):
    """(mínimo, máximo, texto) de caras recomendadas para esta pieza."""
    nz = nozzle_key(nozzle)
    idx, side = size_class(area, dims)
    lo, hi = FACES[nz][idx]
    if kind == 'MECH':
        lo, hi = 5_000, 20_000
    elif kind == 'SMOOTH':
        lo, hi = int(lo * 0.6), int((lo + hi) / 2)
    return lo, hi, SIZES[idx], side


def faces_check(n_faces, nozzle, area, dims, kind='SMOOTH'):
    """Para el análisis: ('ok'|'warn', texto)."""
    lo, hi, size, _side = face_target(nozzle, area, dims, kind)
    nz = str(nozzle_key(nozzle)).replace('.', ',')
    if n_faces > hi * 1.25:
        return 'warn', (f'Malla sobredimensionada: para boquilla {nz} y tamaño {size} bastan '
                        f'{fmt_k(lo)}–{fmt_k(hi)} caras. Usa «Diezmar inteligente».')
    return 'ok', f'bien para boquilla {nz} y tamaño {size} ({fmt_k(lo)}–{fmt_k(hi)})'


# --------------------------------------------------------------------------- desviación
def _sample(V, F, n, rng):
    """Puntos repartidos por la superficie (proporcional al área) más todos los vértices si caben."""
    a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    ar = np.linalg.norm(np.cross(b - a, c - a), axis=1)
    tot = ar.sum()
    if tot <= 0:
        return V.copy()
    idx = rng.choice(len(F), size=n, p=ar / tot)
    r1, r2 = rng.random(n), rng.random(n)
    s = np.sqrt(r1)
    P = (1 - s)[:, None] * a[idx] + (s * (1 - r2))[:, None] * b[idx] + (s * r2)[:, None] * c[idx]
    return P


def _tree(V, F):
    return BVHTree.FromPolygons(V.tolist(), F.tolist(), all_triangles=True)


def _dist(tree, P):
    out = np.empty(len(P))
    fn = tree.find_nearest
    for i, p in enumerate(P):
        hit = fn(Vector(p))
        out[i] = hit[3] if hit[3] is not None else 0.0
    return out


def deviation(tree_a, Pa, Vb, Fb, rng, n=SAMPLES):
    """Hausdorff simétrico aproximado (mm): puntos de A contra B y puntos de B contra A."""
    tree_b = _tree(Vb, Fb)
    d1 = _dist(tree_b, Pa)
    d2 = _dist(tree_a, _sample(Vb, Fb, n, rng))
    d = np.concatenate([d1, d2])
    return {'max': float(d.max()), 'mean': float(d.mean()), 'p99': float(np.percentile(d, 99))}


# --------------------------------------------------------------------------- diezmar sobre el original
def _decimated_arrays(context, obj, ratio, mm):
    """Diezma una COPIA temporal del original (nunca encadena pasos) y devuelve la malla en mm."""
    tmp = obj.copy()
    tmp.data = obj.data
    context.scene.collection.objects.link(tmp)
    try:
        for m in list(tmp.modifiers):
            tmp.modifiers.remove(m)
        mod = tmp.modifiers.new('Doctor_diezmar', 'DECIMATE')
        mod.decimate_type = 'COLLAPSE'
        mod.ratio = float(ratio)
        mod.use_collapse_triangulate = True
        context.view_layer.update()
        graph = context.evaluated_depsgraph_get()
        V, F, mat = doctor.read_arrays(context, tmp, mm)
        me = bpy.data.meshes.new_from_object(tmp.evaluated_get(graph), preserve_all_data_layers=True,
                                             depsgraph=graph)
    finally:
        bpy.data.objects.remove(tmp, do_unlink=True)
    return V, F, me


def _heat_colors(d, tol):
    """0 → verde · tol/2 → amarillo · ≥ tol → rojo."""
    t = np.clip(d / max(tol, 1e-9), 0, 1)
    r = np.clip(t * 2, 0, 1)
    g = np.clip(2 - t * 2, 0, 1)
    b = np.full_like(t, 0.15)
    return np.column_stack([r * 0.95 + 0.05, g * 0.8 + 0.1, b, np.ones_like(t)])


def vertex_heat(Vr, Fr, Porig, obj):
    """Desviación por vértice del objeto: para cada punto del original, la distancia a la cara más
    cercana del resultado; cada cara se queda con su peor punto y cada vértice con su peor cara."""
    tree = _tree(Vr, Fr)
    face_d = np.zeros(len(Fr))
    fn = tree.find_nearest
    for p in Porig:
        hit = fn(Vector(p))
        if hit[2] is not None and hit[3] > face_d[hit[2]]:
            face_d[hit[2]] = hit[3]
    # índices de vértice del objeto (los triángulos de read_arrays usan los vértices de la malla)
    vd = np.zeros(len(obj.data.vertices))
    np.maximum.at(vd, Fr[:, 0], face_d); np.maximum.at(vd, Fr[:, 1], face_d); np.maximum.at(vd, Fr[:, 2], face_d)
    return vd


def apply_heat(obj, d_vertices, tol):
    """Color por vértice con la desviación (mm) de cada punto respecto al original."""
    me = obj.data
    if HEAT_ATTR in me.color_attributes:
        me.color_attributes.remove(me.color_attributes[HEAT_ATTR])
    attr = me.color_attributes.new(HEAT_ATTR, 'FLOAT_COLOR', 'POINT')
    attr.data.foreach_set('color', _heat_colors(d_vertices, tol).astype(np.float32).ravel())
    try:
        me.color_attributes.active_color = attr
    except (AttributeError, TypeError):
        pass
    me.update()


def smart_decimate(context, obj, nozzle=0.4, kind='SMOOTH', unit='AUTO', progress=None):
    """Diezma por pasos sobre el original y se queda con el último que cumple la desviación de la
    boquilla. Devuelve (objeto nuevo o None si no hace falta, info)."""
    t0 = time.time()
    say = progress or (lambda _t: None)
    code, mm = common.resolve_unit(context.scene, unit, obj)
    V0, F0, _mat0 = doctor.read_arrays(context, obj, mm)
    n0 = len(F0)
    if n0 < 500:
        raise common.AddonError('La malla tiene muy pocas caras para diezmar.')
    nz = nozzle_key(nozzle)
    tol = DEVIATION[nz]
    area = surface_area(V0, F0)
    dims = V0.max(0) - V0.min(0)
    lo, hi, size, side = face_target(nz, area, dims, kind)
    floor = max(1_000, {'DETAIL': lo, 'SMOOTH': lo, 'MECH': 5_000}.get(kind, lo))
    info = {'faces_before': n0, 'faces_after': n0, 'tolerance': tol, 'nozzle': nz, 'kind': kind,
            'size': size, 'side_mm': side, 'area_mm2': area, 'dims': dims.tolist(), 'target': (lo, hi),
            'steps': [], 'notes': [], 'unit': code}
    if n0 <= floor * 1.05:
        info['notes'].append(f'Ya está bien: {fmt_k(n0)} caras para boquilla {str(nz).replace(".", ",")} y tamaño '
                             f'{size} ({fmt_k(lo)}–{fmt_k(hi)}). No hace falta diezmar.')
        info['seconds'] = time.time() - t0
        return None, info

    rng = np.random.default_rng(7)
    tree0 = _tree(V0, F0)
    P0 = _sample(V0, F0, SAMPLES, rng)
    # pasos sobre el original; se empieza cerca del máximo recomendado para no perder tiempo
    ratios = sorted({r for r in STEPS if n0 * r >= floor * 0.98} | {min(0.85, hi / n0), floor / n0}, reverse=True)
    ratios = [r for r in ratios if r < 0.9]
    start = min(range(len(ratios)), key=lambda i: abs(ratios[i] - hi / n0))
    best = None            # (ratio, dev, mesh)
    fail_ratio = None
    tried = {}

    def probe(r):
        say(f'Diezmando a {fmt_k(n0 * r)} caras…')
        V, F, me = _decimated_arrays(context, obj, r, mm)
        dev = deviation(tree0, P0, V, F, rng)
        info['steps'].append({'faces': len(F), 'max': dev['max'], 'mean': dev['mean'], 'ok': dev['max'] <= tol})
        tried[r] = dev['max'] <= tol
        return dev, me

    i = start
    dev, me = probe(ratios[i])
    if dev['max'] <= tol:                  # cumple: seguir bajando hasta que deje de cumplir
        best = (ratios[i], dev, me)
        for r in ratios[i + 1:]:
            dev, me = probe(r)
            if dev['max'] <= tol:
                bpy.data.meshes.remove(best[2]); best = (r, dev, me)
            else:
                bpy.data.meshes.remove(me); fail_ratio = r
                break
    else:                                  # no cumple: subir hasta que cumpla
        bpy.data.meshes.remove(me)
        fail_ratio = ratios[i]
        for r in reversed(ratios[:i]):
            dev, me = probe(r)
            if dev['max'] <= tol:
                best = (r, dev, me)
                break
            bpy.data.meshes.remove(me); fail_ratio = r
    # afinar entre el último que cumple y el primero que no (dos pasadas)
    if best is not None and fail_ratio is not None:
        hi_r, lo_r = best[0], fail_ratio
        for _ in range(2):
            mid = math.sqrt(hi_r * lo_r)
            if n0 * (hi_r - mid) < 2_000:
                break
            say(f'Afinando: {fmt_k(n0 * mid)} caras…')
            V, F, me = _decimated_arrays(context, obj, mid, mm)
            dev = deviation(tree0, P0, V, F, rng)
            info['steps'].append({'faces': len(F), 'max': dev['max'], 'mean': dev['mean'], 'ok': dev['max'] <= tol})
            if dev['max'] <= tol:
                bpy.data.meshes.remove(best[2])
                best = (mid, dev, me)
                hi_r = mid
            else:
                bpy.data.meshes.remove(me)
                lo_r = mid
    if best is None:
        info['notes'].append(f'No se puede quitar ni un 30 % de caras sin pasar de {es(tol, 2)} mm de desviación: '
                             'la malla ya está ajustada a su detalle. Se queda como está.')
        info['seconds'] = time.time() - t0
        return None, info

    # resultado: objeto nuevo con la malla elegida; el original se oculta y no se toca
    say('Reparando la malla diezmada…')
    _r, dev, me = best
    col = obj.users_collection[0] if obj.users_collection else context.scene.collection
    out = obj.copy()
    out.data = me
    me.name = f'{obj.data.name}_diezmado'
    out.name = f'{obj.name}_diezmado'
    for m in list(out.modifiers):
        out.modifiers.remove(m)
    col.objects.link(out)
    out.matrix_world = obj.matrix_world.copy()
    closed_before = mo.is_closed(mo.edge_table(mo.weld(V0, F0)[1]))
    notes = _repair_light(context, out, mm, closed_before)
    info['notes'] += notes

    # mapa de calor: cuánto se separa el original de cada cara del resultado (es en el centro de los
    # triángulos donde se pierde forma, no en los vértices, que quedan sobre el original)
    say('Midiendo dónde se ha perdido forma…')
    Vr, Fr, _m = doctor.read_arrays(context, out, mm)
    dv = vertex_heat(Vr, Fr, np.vstack([P0, V0]), out)
    apply_heat(out, dv, tol)
    table = mo.edge_table(mo.weld(Vr, Fr)[1])
    info.update({'faces_after': len(Fr), 'max': dev['max'], 'mean': dev['mean'], 'p99': dev['p99'],
                 'closed': bool(mo.is_closed(table)), 'nonmanifold': int((table['cnt'] > 2).sum()),
                 'red_share': float((dv > tol * 0.75).mean()), 'seconds': time.time() - t0})
    out[common.UNIT_PROP] = code
    out['doctor_diezmado'] = (f'{n0}→{len(Fr)} caras · desv. máx {dev["max"]:.3f} mm · media {dev["mean"]:.3f} mm '
                              f'· boquilla {nz}')
    obj.hide_set(True)
    for o in context.selected_objects:
        o.select_set(False)
    out.select_set(True)
    context.view_layer.objects.active = out
    return out, info


def _repair_light(context, obj, mm, closed_before):
    """Diezmar puede abrir o pellizcar la malla: soldar, quitar triángulos rotos, normales coherentes
    y, si estaba cerrada y se ha abierto, cerrar los agujeros."""
    notes = []
    V, F, mat = doctor.mesh_arrays(obj.data)
    Vw, Fw, keep = mo.weld(V, F, tol=1e-4 / max(mm, 1e-9))
    if len(Fw) != len(F) or len(Vw) != len(V):
        new = doctor.new_mesh(obj.data.name, Vw, Fw, [s.material for s in obj.material_slots] or None, mat[keep])
        old = obj.data
        obj.data = new
        if old.users == 0:
            bpy.data.meshes.remove(old)
        if len(F) - len(Fw):
            notes.append(f'{len(F) - len(Fw)} triángulos rotos quitados')
    doctor._recalc_normals(obj)
    V2, F2, _m = doctor.mesh_arrays(obj.data)
    table = mo.edge_table(F2)
    if closed_before and not mo.is_closed(table):
        holes = doctor._fill_holes(obj)
        doctor._recalc_normals(obj)
        if holes:
            notes.append(f'{holes} agujero(s) que abrió el diezmado, cerrados')
    notes.append('normales revisadas')
    return notes


def summary_lines(info):
    """Texto del antes y el después para el panel o el informe."""
    if info['faces_after'] == info['faces_before']:
        return list(info['notes'])
    nz = str(info['nozzle']).replace('.', ',')
    lines = [f'{fmt_k(info["faces_before"])} → {fmt_k(info["faces_after"])} caras '
             f'({100 * (1 - info["faces_after"] / info["faces_before"]):.0f} % menos)',
             f'desviación máx. {es(info["max"], 3)} mm · media {es(info["mean"], 3)} mm '
             f'(límite {es(info["tolerance"], 2)} mm, boquilla {nz})',
             f'pieza {info["size"]} · {KIND_NAMES.get(info["kind"], "")} · rango {fmt_k(info["target"][0])}–'
             f'{fmt_k(info["target"][1])}',
             'malla cerrada' if info.get('closed') else 'OJO: la malla ha quedado abierta, pásale «Dejar perfecto»']
    return lines + [n for n in info['notes'] if n != 'normales revisadas']


# --------------------------------------------------------------------------- foto del mapa de calor
def render_heat(context, obj, path, size=(900, 700)):
    """Foto del mapa de calor (Workbench, colores por vértice), vista 3/4. Para el informe de 3D LAB.
    No deja nada en la escena: cámara, luz y ajustes se restauran."""
    import math as _m
    scn = context.scene
    keep = {'engine': scn.render.engine, 'x': scn.render.resolution_x, 'y': scn.render.resolution_y,
            'pct': scn.render.resolution_percentage, 'cam': scn.camera, 'path': scn.render.filepath,
            'fmt': scn.render.image_settings.file_format}
    sh = scn.display.shading
    keep_sh = (sh.light, sh.color_type, getattr(sh, 'show_cavity', False))
    hidden = [o for o in scn.objects if o is not obj and not o.hide_render]
    for o in hidden:
        o.hide_render = True
    cam_data = bpy.data.cameras.new('_heat_cam')
    cam = bpy.data.objects.new('_heat_cam', cam_data)
    scn.collection.objects.link(cam)
    try:
        scn.render.engine = 'BLENDER_WORKBENCH'
        sh.light = 'STUDIO'
        sh.color_type = 'VERTEX'
        try:
            sh.show_cavity = True
        except AttributeError:
            pass
        scn.render.resolution_x, scn.render.resolution_y = size
        scn.render.resolution_percentage = 100
        scn.render.image_settings.file_format = 'PNG'
        corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
        lo = Vector([min(c[i] for c in corners) for i in range(3)])
        hi = Vector([max(c[i] for c in corners) for i in range(3)])
        center = (lo + hi) / 2
        radius = max((hi - lo).length / 2, 1e-6)
        direction = Vector((1.0, -1.25, 0.8)).normalized()
        cam_data.type = 'ORTHO'
        cam_data.ortho_scale = radius * 2.25
        cam_data.clip_start = radius * 0.01
        cam_data.clip_end = radius * 20
        cam.location = center + direction * radius * 5
        cam.rotation_euler = (center - cam.location).to_track_quat('-Z', 'Y').to_euler()
        scn.camera = cam
        scn.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
    finally:
        scn.camera = keep['cam']
        bpy.data.objects.remove(cam, do_unlink=True)
        bpy.data.cameras.remove(cam_data)
        for o in hidden:
            o.hide_render = False
        scn.render.engine = keep['engine']
        scn.render.resolution_x, scn.render.resolution_y = keep['x'], keep['y']
        scn.render.resolution_percentage = keep['pct']
        scn.render.filepath = keep['path']
        scn.render.image_settings.file_format = keep['fmt']
        sh.light, sh.color_type = keep_sh[0], keep_sh[1]
        try:
            sh.show_cavity = keep_sh[2]
        except AttributeError:
            pass
    return path
