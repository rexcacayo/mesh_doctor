# SPDX-FileCopyrightText: 2026 Ricardo Lugaresi
# SPDX-License-Identifier: GPL-3.0-or-later

"""Mesh Doctor: analizar y dejar la malla perfecta para imprimir o separar colores.

Todo trabaja sobre una copia: el original se oculta y nunca se modifica.
Los colores (materiales por cara) se conservan en cada paso.
"""
import time

import bmesh
import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from . import common
from . import meshops as mo

_LAST = {}


# --------------------------------------------------------------------------- lectura / escritura
def read_arrays(context, obj, mm):
    graph = context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(graph)
    me = ev.to_mesh()
    try:
        me.calc_loop_triangles()
        nt = len(me.loop_triangles)
        tri = np.empty(nt * 3, np.int64); me.loop_triangles.foreach_get('vertices', tri)
        pidx = np.empty(nt, np.int64); me.loop_triangles.foreach_get('polygon_index', pidx)
        pmat = np.empty(len(me.polygons), np.int64); me.polygons.foreach_get('material_index', pmat)
        co = np.empty(len(me.vertices) * 3); me.vertices.foreach_get('co', co)
    finally:
        ev.to_mesh_clear()
    M = np.array(obj.matrix_world)
    V = (co.reshape(-1, 3) @ M[:3, :3].T + M[:3, 3]) * mm
    F = tri.reshape(-1, 3)
    if np.linalg.det(M[:3, :3]) < 0:
        F = F[:, ::-1]
    mat = pmat[pidx] if len(pmat) else np.zeros(len(F), np.int64)
    return V, F, mat


def new_mesh(name, V, F, materials=None, mat_index=None):
    me = bpy.data.meshes.new(name)
    me.vertices.add(len(V))
    me.vertices.foreach_set('co', V.astype(np.float32).ravel())
    me.loops.add(len(F) * 3)
    me.loops.foreach_set('vertex_index', F.astype(np.int32).ravel())
    me.polygons.add(len(F))
    me.polygons.foreach_set('loop_start', np.arange(0, len(F) * 3, 3, dtype=np.int32))
    if materials:
        for m in materials:
            me.materials.append(m)
        if mat_index is not None and len(mat_index):
            me.polygons.foreach_set('material_index', mat_index.astype(np.int32))
    me.update(calc_edges=True)
    return me


def mesh_arrays(me):
    me.calc_loop_triangles()
    nt = len(me.loop_triangles)
    tri = np.empty(nt * 3, np.int64); me.loop_triangles.foreach_get('vertices', tri)
    pidx = np.empty(nt, np.int64); me.loop_triangles.foreach_get('polygon_index', pidx)
    pmat = np.empty(len(me.polygons), np.int64); me.polygons.foreach_get('material_index', pmat)
    co = np.empty(len(me.vertices) * 3); me.vertices.foreach_get('co', co)
    return co.reshape(-1, 3), tri.reshape(-1, 3), (pmat[pidx] if len(pmat) else np.zeros(nt, np.int64))


# --------------------------------------------------------------------------- comprobaciones
def _inside(tree, p, direction=Vector((0.3713, 0.5521, 0.7466))):
    """¿El punto está dentro de la malla del árbol? (paridad de cruces de un rayo)."""
    hits, o, steps = 0, Vector(p), 0
    while steps < 200:
        loc, _n, _i, d = tree.ray_cast(o, direction)
        if loc is None:
            break
        hits += 1
        o = loc + direction * 1e-4
        steps += 1
    return hits % 2 == 1


def _self_intersections(V, F, limit_faces=600000):
    """Pares de triángulos que se cruzan (sin contar los vecinos que comparten vértice)."""
    if len(F) > limit_faces:
        return None
    tree = BVHTree.FromPolygons(V.tolist(), F.tolist(), all_triangles=True)
    pairs = tree.overlap(tree)
    if not pairs:
        return 0
    P = np.array(pairs, dtype=np.int64)
    P = P[P[:, 0] < P[:, 1]]
    if not len(P):
        return 0
    A, B = F[P[:, 0]], F[P[:, 1]]
    share = (A[:, :, None] == B[:, None, :]).any(axis=(1, 2))
    return int((~share).sum())


def _thin_share(V, F, min_wall, samples=20000):
    nrm = mo.vertex_normals_full(V, F)
    tree = BVHTree.FromPolygons(V.tolist(), F.tolist(), all_triangles=True)
    idx = np.unique(F)
    if len(idx) > samples:
        idx = np.random.default_rng(1).choice(idx, samples, replace=False)
    thin = 0
    for i in idx:
        o = Vector(V[i] - nrm[i] * 1e-3)
        hit = tree.ray_cast(o, Vector(-nrm[i]), min_wall)
        if hit[0] is not None and hit[3] > 1e-3:
            thin += 1
    return thin / max(1, len(idx))


def analyze(context, obj, nozzle=0.4, unit='AUTO', deep=True):
    """Lista de comprobaciones con su gravedad: 'ok', 'warn' o 'bad'."""
    t0 = time.time()
    code, mm = common.resolve_unit(context.scene, unit, obj)
    V0, F0, mat0 = read_arrays(context, obj, mm)
    checks = []

    def add(key, label, value, sev, detail=''):
        checks.append({'key': key, 'label': label, 'value': value, 'sev': sev, 'detail': detail})

    dims = V0.max(0) - V0.min(0) if len(V0) else np.zeros(3)
    big = float(dims.max())
    add('size', 'Tamaño', f'{dims[0]:.1f} × {dims[1]:.1f} × {dims[2]:.1f} mm',
        'warn' if big < 5 or big > 1000 else 'ok',
        'Muy pequeño o muy grande: revisa las unidades' if big < 5 or big > 1000 else f'1 unidad = 1 {common.UNIT_NAMES.get(code, code)}')
    keys = np.round(V0 / 1e-4).astype(np.int64)
    ndup = len(V0) - len(np.unique(keys, axis=0))
    V, F, keep = mo.weld(V0, F0)
    mat = mat0[keep]
    ndeg = len(F0) - len(F)
    add('dupes', 'Vértices duplicados', ndup, 'warn' if ndup else 'ok', 'se sueldan solos' if ndup else '')
    add('degen', 'Triángulos rotos o repetidos', ndeg, 'warn' if ndeg else 'ok', 'se quitan solos' if ndeg else '')
    table = mo.edge_table(F)
    tj = 0
    if not mo.is_closed(table):
        for _ in range(3):
            V, F, mat, n = mo.fix_t_junctions(V, F, mat)
            if not n:
                break
            tj += n
        table = mo.edge_table(F)
    add('tjunc', 'Uniones en T (fronteras sin coser)', tj, 'warn' if tj else 'ok', 'se cosen solas' if tj else '')
    nopen = int((table['cnt'] == 1).sum())
    nmulti = int((table['cnt'] > 2).sum())
    holes = len(mo.boundary_loops_all(table)) if nopen else 0
    add('holes', 'Agujeros', holes, 'bad' if holes else 'ok', f'{nopen} aristas abiertas' if nopen else 'malla cerrada')
    add('nonman', 'Aristas no-manifold', nmulti, 'bad' if nmulti else 'ok', 'aristas con más de dos caras' if nmulti else '')
    nori = mo.orientation_errors(table)
    add('orient', 'Normales incoherentes', nori, 'bad' if nori else 'ok', 'caras mirando hacia dentro' if nori else '')

    flab = mo.vertex_components(len(V), F)
    st = mo.component_stats(V, F, flab, table)
    ncomp = len(st['faces'])
    total_area = st['area'].sum()
    main = int(np.argmax(st['area']))
    small = np.nonzero((st['area'] < max(1.0, 0.005 * total_area)) & (np.arange(ncomp) != main))[0]
    inverted = np.nonzero((~st['open']) & (st['volume'] < 0))[0]
    internal = []
    if ncomp > 1 and not st['open'][main]:
        fm = np.nonzero(flab == main)[0]
        used, inv = np.unique(F[fm], return_inverse=True)
        mtree = BVHTree.FromPolygons(V[used].tolist(), inv.reshape(-1, 3).tolist(), all_triangles=True)
        for c in range(ncomp):
            if c == main or c in set(small.tolist()):
                continue
            if np.all(st['lo'][c] >= st['lo'][main]) and np.all(st['hi'][c] <= st['hi'][main]):
                p = V[F[np.nonzero(flab == c)[0][0], 0]]
                if _inside(mtree, p):
                    internal.append(c)
    add('parts', 'Piezas', ncomp, 'ok' if ncomp == 1 else 'warn', 'una sola pieza' if ncomp == 1 else 'piezas separadas o solapadas')
    add('specks', 'Motas y trocitos sueltos', len(small), 'warn' if len(small) else 'ok', 'se quitan solos' if len(small) else '')
    # una pieza «del revés» metida dentro de otra es un hueco encerrado, no un error grave
    voids = [c for c in internal if st['volume'][c] < 0]
    internal = [c for c in internal if st['volume'][c] >= 0]
    inverted = [c for c in inverted.tolist() if c not in set(voids)]
    add('inner', 'Capas internas', len(internal), 'warn' if internal else 'ok', 'piezas metidas dentro de otra' if internal else '')
    add('voids', 'Huecos encerrados', len(voids), 'warn' if voids else 'ok', 'se rellenan al reparar' if voids else '')
    add('inverted', 'Piezas del revés', len(inverted), 'bad' if len(inverted) else 'ok', 'se dan la vuelta solas' if len(inverted) else '')
    if deep:
        si = 0 if obj.get('doctor_solido') else _self_intersections(V, F)
        if si is None:
            add('cross', 'Autointersecciones', 'sin medir', 'warn', 'modelo muy grande: se resuelven al unir piezas')
        else:
            add('cross', 'Autointersecciones', si, 'bad' if si else 'ok', 'la malla se atraviesa a sí misma' if si else '')
        min_wall = 2 * nozzle
        thin = _thin_share(V, F, min_wall)
        add('thin', f'Más fino que {min_wall:.1f} mm', f'{thin * 100:.1f} %',
            'warn' if thin > 0.005 else 'ok',
            'zonas finas: revisa que salgan (o usa una boquilla más fina)' if thin > 0.005 else '')
    ncol = len(np.unique(mat))
    add('colors', 'Colores', ncol, 'ok', 'se conservan al reparar' if ncol > 1 else 'un solo color')
    add('faces', 'Caras', f'{len(F0):,}'.replace(',', '.'), 'warn' if len(F0) > 2_500_000 else 'ok',
        'muchas: conviene reducir' if len(F0) > 2_500_000 else '')
    sev = 'bad' if any(c['sev'] == 'bad' for c in checks) else 'warn' if any(c['sev'] == 'warn' for c in checks) else 'ok'
    report = {'checks': checks, 'verdict': sev, 'seconds': time.time() - t0, 'unit': code}
    _LAST[obj.name] = report
    return report


# --------------------------------------------------------------------------- reparar
def _fill_holes(obj, smooth_rounds=8):
    """Cierra los agujeros con un parche y lo relaja para que no quede una tapa plana."""
    me = obj.data
    bm = bmesh.new()
    bm.from_mesh(me)
    try:
        edges = [e for e in bm.edges if e.is_boundary]
        if not edges:
            return 0
        res = bmesh.ops.holes_fill(bm, edges=edges, sides=0)
        faces = res['faces']
        n = len(faces)
        if not faces:
            return 0
        # color del parche: el de sus vecinas
        for f in faces:
            neigh = [lf.material_index for e in f.edges for lf in e.link_faces if lf is not f]
            if neigh:
                f.material_index = max(set(neigh), key=neigh.count)
        tri = bmesh.ops.triangulate(bm, faces=faces, quad_method='BEAUTY', ngon_method='BEAUTY')['faces']
        patch = set(tri)
        border = {v for f in patch for v in f.verts if any(lf not in patch for lf in v.link_faces)}
        lens = [e.calc_length() for f in patch for e in f.edges]
        avg = sum(lens) / max(1, len(lens))
        for _ in range(4):                                   # refinar triángulos largos
            long_edges = list({e for f in patch for e in f.edges if e.calc_length() > avg * 1.5})
            if not long_edges:
                break
            out = bmesh.ops.subdivide_edges(bm, edges=long_edges, cuts=1, use_grid_fill=False)
            new_faces = [g for g in out['geom'] if isinstance(g, bmesh.types.BMFace)]
            bmesh.ops.triangulate(bm, faces=[f for f in new_faces if len(f.verts) > 3])
            patch = {f for v in out['geom_inner'] if isinstance(v, bmesh.types.BMVert) for f in v.link_faces} | \
                {f for f in patch if f.is_valid}
        inner = [v for f in patch if f.is_valid for v in f.verts if v not in border]
        inner = list(set(inner))
        for _ in range(smooth_rounds):
            bmesh.ops.smooth_vert(bm, verts=inner, factor=0.5, use_axis_x=True, use_axis_y=True, use_axis_z=True)
        bm.to_mesh(me)
        me.update()
        return n
    finally:
        bm.free()


def _recalc_normals(obj):
    me = obj.data
    bm = bmesh.new()
    bm.from_mesh(me)
    try:
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
        bm.to_mesh(me)
        me.update()
    finally:
        bm.free()


def _boolean_union(context, target, other):
    solvers = set(bpy.types.BooleanModifier.bl_rna.properties['solver'].enum_items.keys())
    mod = target.modifiers.new('Doctor_union', 'BOOLEAN')
    mod.operation = 'UNION'
    mod.solver = 'MANIFOLD' if 'MANIFOLD' in solvers else 'EXACT'
    mod.object = other
    try:
        context.view_layer.update()
        graph = context.evaluated_depsgraph_get()
        new = bpy.data.meshes.new_from_object(target.evaluated_get(graph), preserve_all_data_layers=True, depsgraph=graph)
    finally:
        target.modifiers.remove(mod)
    V, F, _m = mesh_arrays(new)
    t = mo.edge_table(F) if len(F) else None
    if t is None or int((t['cnt'] == 1).sum()):
        bpy.data.meshes.remove(new)
        return False
    old = target.data
    target.data = new
    if old.users == 0:
        bpy.data.meshes.remove(old)
    return True


def _resolve_self(context, obj, col):
    """Quita los cruces de la malla consigo misma: booleana exacta en modo «auto» (une la
    malla con nada, resolviendo sus propias intersecciones). Solo para mallas medianas."""
    empty = bpy.data.collections.new('Doctor_vacia')
    mod = obj.modifiers.new('Doctor_self', 'BOOLEAN')
    try:
        mod.operation = 'UNION'
        mod.solver = 'EXACT'
        mod.operand_type = 'COLLECTION'
        mod.collection = empty
        mod.use_self = True
        mod.use_hole_tolerant = True
        context.view_layer.update()
        graph = context.evaluated_depsgraph_get()
        new = bpy.data.meshes.new_from_object(obj.evaluated_get(graph), preserve_all_data_layers=True, depsgraph=graph)
    finally:
        obj.modifiers.remove(mod)
        bpy.data.collections.remove(empty)
    V, F, _m = mesh_arrays(new)
    t = mo.edge_table(F) if len(F) else None
    if t is None or int((t['cnt'] == 1).sum()):
        bpy.data.meshes.remove(new)
        return False
    old = obj.data
    obj.data = new
    if old.users == 0:
        bpy.data.meshes.remove(old)
    return True


def repair(context, obj, unit='AUTO', drop_specks=True, drop_internal=True, fill=True, merge_parts=True,
           max_faces=0):
    """Deja la malla lista. Devuelve (objeto nuevo, lista de lo que se ha hecho)."""
    t0 = time.time()
    code, mm = common.resolve_unit(context.scene, unit, obj)
    V, F, mat = read_arrays(context, obj, mm)
    done = []
    n0 = len(F)
    V, F, keep = mo.weld(V, F)
    mat = mat[keep]
    if n0 - len(F):
        done.append(f'{n0 - len(F)} triángulos rotos o repetidos quitados')
    table = mo.edge_table(F)
    tj = 0
    for _ in range(4):
        if mo.is_closed(table):
            break
        V, F, mat, n = mo.fix_t_junctions(V, F, mat)
        if not n:
            break
        tj += n
        table = mo.edge_table(F)
    if tj:
        done.append(f'{tj} uniones en T cosidas')

    flab = mo.vertex_components(len(V), F)
    st = mo.component_stats(V, F, flab, table)
    ncomp = len(st['faces'])
    main = int(np.argmax(st['area']))
    remove = set()
    if drop_specks and ncomp > 1:
        small = np.nonzero((st['area'] < max(1.0, 0.005 * st['area'].sum())) & (np.arange(ncomp) != main))[0]
        remove |= set(small.tolist())
        if len(small):
            done.append(f'{len(small)} motas o trocitos sueltos quitados')
    if drop_internal and ncomp > 1 and not st['open'][main]:
        fm = np.nonzero(flab == main)[0]
        used, inv = np.unique(F[fm], return_inverse=True)
        mtree = BVHTree.FromPolygons(V[used].tolist(), inv.reshape(-1, 3).tolist(), all_triangles=True)
        inner = 0
        for c in range(ncomp):
            if c == main or c in remove:
                continue
            if np.all(st['lo'][c] >= st['lo'][main]) and np.all(st['hi'][c] <= st['hi'][main]):
                p = V[F[np.nonzero(flab == c)[0][0], 0]]
                if _inside(mtree, p):
                    remove.add(c); inner += 1
        if inner:
            done.append(f'{inner} capas internas quitadas')
    if remove:
        keepf = ~np.isin(flab, list(remove))
        F, mat, flab = F[keepf], mat[keepf], flab[keepf]
        used, inv = np.unique(F, return_inverse=True)
        V, F = V[used], inv.reshape(-1, 3)

    col = obj.users_collection[0] if obj.users_collection else context.scene.collection
    mats = [s.material for s in obj.material_slots]
    me = new_mesh(f'{obj.name}_ok', V / mm, F, mats, mat)
    out = bpy.data.objects.new(f'{obj.name}_ok', me)
    col.objects.link(out)
    try:
        if fill:
            nh = _fill_holes(out)
            if nh:
                done.append(f'{nh} agujero(s) cerrado(s)')
        _recalc_normals(out)
        done.append('normales orientadas hacia fuera')
        if merge_parts:
            Vb, Fb, mb = mesh_arrays(out.data)
            t = mo.edge_table(Fb)
            fl = mo.vertex_components(len(Vb), Fb)
            s2 = mo.component_stats(Vb, Fb, fl, t)
            nc = len(s2['faces'])
            if nc > 1:
                lo, hi = s2['lo'], s2['hi']
                overl = [c for c in range(nc) if not s2['open'][c] and any(
                    d != c and np.all(lo[c] <= hi[d]) and np.all(lo[d] <= hi[c]) for d in range(nc))]
                if 1 < len(overl) <= 60:
                    order = sorted(overl, key=lambda c: -s2['area'][c])
                    rest = [c for c in range(nc) if c not in overl]
                    def sub(cs):
                        m = np.isin(fl, cs)
                        Fs = Fb[m]; u, iv = np.unique(Fs, return_inverse=True)
                        return Vb[u], iv.reshape(-1, 3), mb[m]
                    v0, f0, m0 = sub([order[0]])
                    base_me = new_mesh('Doctor_base', v0, f0, mats, m0)
                    out_old = out.data
                    out.data = base_me
                    joined = 1
                    for c in order[1:]:
                        vc, fc, mcc = sub([c])
                        tmp_me = new_mesh('Doctor_tmp', vc, fc, mats, mcc)
                        tmp = bpy.data.objects.new('Doctor_tmp', tmp_me)
                        col.objects.link(tmp)
                        ok = _boolean_union(context, out, tmp)
                        common.remove_objects([tmp])
                        if ok:
                            joined += 1
                    if rest:
                        vr, fr, mr = sub(rest)
                        Vx, Fx, mx = mesh_arrays(out.data)
                        merged = new_mesh(out.data.name, np.vstack([Vx, vr]), np.vstack([Fx, fr + len(Vx)]),
                                          mats, np.concatenate([mx, mr]))
                        old = out.data; out.data = merged
                        if old.users == 0:
                            bpy.data.meshes.remove(old)
                    if out_old.users == 0:
                        bpy.data.meshes.remove(out_old)
                    done.append(f'{joined} piezas solapadas unidas en un sólido')
        Vc, Fc, _mc = mesh_arrays(out.data)
        si = _self_intersections(Vc, Fc)
        unresolved = False
        if si and (si > 2000 or len(Fc) > 200_000):
            unresolved = True            # demasiados cruces: rehacer con vóxeles es más rápido y seguro
        elif si:
            if _resolve_self(context, out, col):
                _recalc_normals(out)
                done.append(f'{si} cruces de la malla resueltos')
            else:
                unresolved = True
        elif si is None:
            done.append('modelo muy grande: los cruces no se han comprobado')
        # repaso final: las booleanas pueden dejar vértices repetidos o triángulos de área cero
        Vf, Ff, mf = mesh_arrays(out.data)
        Vw, Fw, kw = mo.weld(Vf * mm, Ff)
        if len(Fw) != len(Ff) or len(Vw) != len(Vf):
            new = new_mesh(out.data.name, Vw / mm, Fw, mats, mf[kw])
            old = out.data; out.data = new
            if old.users == 0:
                bpy.data.meshes.remove(old)
            _recalc_normals(out)
        if max_faces and len(out.data.polygons) > max_faces:
            ratio = max_faces / len(out.data.polygons)
            mod = out.modifiers.new('Doctor_reducir', 'DECIMATE')
            mod.ratio = ratio
            context.view_layer.update()
            graph = context.evaluated_depsgraph_get()
            new = bpy.data.meshes.new_from_object(out.evaluated_get(graph), preserve_all_data_layers=True, depsgraph=graph)
            out.modifiers.remove(mod)
            old = out.data; out.data = new
            if old.users == 0:
                bpy.data.meshes.remove(old)
            done.append(f'caras reducidas a {len(new.polygons):,}'.replace(',', '.'))
        # ¿Sigue sin ser un sólido limpio? (cruces o aristas compartidas por más de dos caras)
        Vq, Fq, _mq = mesh_arrays(out.data)
        tq = mo.edge_table(Fq)
        if unresolved or int((tq['cnt'] != 2).sum()):
            # sin pasarse de caras: en un portátil justo, 6 veces más caras que el original es inmanejable
            cap = max_faces or min(1_500_000, max(300_000, 2 * len(Fq)))
            solid = remesh_solid(context, out, 0.0, unit, cap, report=done)
            common.remove_objects([out])
            solid.name = f'{obj.name}_ok'
            out = solid
            done.insert(0, 'la malla se cruzaba consigo misma: se ha rehecho el sólido')
    except Exception:
        common.remove_objects([out])
        raise
    out[common.UNIT_PROP] = code
    out['taller_origen'] = obj.name
    obj.hide_set(True); obj.hide_render = True
    for o in context.selected_objects:
        o.select_set(False)
    out.select_set(True)
    context.view_layer.objects.active = out
    return out, done, time.time() - t0


def auto_voxel(obj, mm):
    """Detalle automático: unas 500 divisiones en el lado mayor (0,05–0,3 mm)."""
    big = max(obj.dimensions) * mm
    return float(min(0.3, max(0.05, big / 500.0)))


def _drop_small_parts(obj, mm, min_mm3=1.0, rel=0.001):
    """Quita trocitos sueltos (y su orientación) tras rehacer con vóxeles."""
    V, F, m = mesh_arrays(obj.data)
    if not len(F):
        return 0
    fl = mo.vertex_components(len(V), F)
    vol6 = np.einsum('ij,ij->i', V[F[:, 0]], np.cross(V[F[:, 1]], V[F[:, 2]])) * mm ** 3
    vols = np.bincount(fl, weights=vol6) / 6.0
    keep_c = np.abs(vols) >= max(min_mm3, rel * abs(vols).max())
    if keep_c.all():
        return 0
    keepf = keep_c[fl]
    F2, m2 = F[keepf], m[keepf]
    u, inv = np.unique(F2, return_inverse=True)
    new = new_mesh(obj.data.name, V[u], inv.reshape(-1, 3), [s.material for s in obj.material_slots] or None, m2)
    old = obj.data; obj.data = new
    if old.users == 0:
        bpy.data.meshes.remove(old)
    return int((~keep_c).sum())


def _decimate(context, obj, max_faces):
    if len(obj.data.polygons) <= max_faces:
        return False
    mod = obj.modifiers.new('Doctor_reducir', 'DECIMATE')
    mod.ratio = max_faces / len(obj.data.polygons)
    context.view_layer.update()
    graph = context.evaluated_depsgraph_get()
    new = bpy.data.meshes.new_from_object(obj.evaluated_get(graph), preserve_all_data_layers=True, depsgraph=graph)
    obj.modifiers.remove(mod)
    old = obj.data; obj.data = new
    if old.users == 0:
        bpy.data.meshes.remove(old)
    return True


def remesh_solid(context, obj, voxel_mm=0.0, unit='AUTO', max_faces=1_500_000, report=None):
    """Rehace el sólido con vóxeles: siempre sale cerrado y sin cruces. Los colores se
    copian de la malla original (cara más cercana)."""
    code, mm = common.resolve_unit(context.scene, unit, obj)
    if voxel_mm <= 0:
        voxel_mm = auto_voxel(obj, mm)
    col = obj.users_collection[0] if obj.users_collection else context.scene.collection
    out = obj.copy(); out.data = obj.data.copy(); out.name = f'{obj.name}_solido'
    col.objects.link(out)
    for m in list(out.modifiers):
        out.modifiers.remove(m)
    # los vóxeles necesitan saber qué es dentro: con agujeros, la pieza se perdía entera
    holes = _fill_holes(out)
    mod = out.modifiers.new('Doctor_remesh', 'REMESH')
    mod.mode = 'VOXEL'
    scale = max(out.matrix_world.to_scale())
    mod.voxel_size = voxel_mm / mm / max(scale, 1e-12)
    mod.use_smooth_shade = False
    context.view_layer.update()
    graph = context.evaluated_depsgraph_get()
    new = bpy.data.meshes.new_from_object(out.evaluated_get(graph), depsgraph=graph)
    out.modifiers.remove(mod)
    out.data = new
    for m in obj.material_slots:
        new.materials.append(m.material)
    if not len(new.polygons):
        common.remove_objects([out])
        raise common.AddonError('No se pudo rehacer el sólido: la malla está demasiado abierta. '
                                'Prueba antes «Dejar perfecto» o un detalle (mm) más grueso.')
    crumbs = _drop_small_parts(out, mm * max(out.matrix_world.to_scale()))
    _recalc_normals(out)
    reduced = _decimate(context, out, max_faces)
    new = out.data
    if report is not None:
        if holes:
            report.append(f'{holes} agujero(s) tapado(s) antes de rehacer')
        report.append(f'sólido rehecho con vóxeles de {voxel_mm:.2f} mm')
        if crumbs:
            report.append(f'{crumbs} trocitos sueltos quitados')
        if reduced:
            report.append(f'caras reducidas a {len(new.polygons):,}'.replace(',', '.'))
    if len(obj.material_slots) > 1:
        V, F, mat = read_arrays(context, obj, 1.0)
        tree = BVHTree.FromPolygons(V.tolist(), F.tolist(), all_triangles=True)
        Mw = np.array(out.matrix_world)
        n = len(new.polygons)
        cen = np.empty(n * 3); new.polygons.foreach_get('center', cen)
        cen = cen.reshape(-1, 3) @ Mw[:3, :3].T + Mw[:3, 3]
        idx = np.zeros(n, np.int64)
        for i in range(n):
            hit = tree.find_nearest(Vector(cen[i]))
            if hit[2] is not None:
                idx[i] = mat[hit[2]]
        new.polygons.foreach_set('material_index', idx.astype(np.int32))
        new.update()
    Vf, Ff, mf = mesh_arrays(out.data)
    Vw, Fw, kw = mo.weld(Vf * mm, Ff)
    if len(Fw) != len(Ff) or len(Vw) != len(Vf):
        rebuilt = new_mesh(out.data.name, Vw / mm, Fw, [m.material for m in obj.material_slots], mf[kw])
        old = out.data; out.data = rebuilt
        if old.users == 0:
            bpy.data.meshes.remove(old)
        _recalc_normals(out)
    out[common.UNIT_PROP] = code
    out['doctor_solido'] = True          # rehecho con vóxeles: no puede cruzarse consigo mismo
    obj.hide_set(True)
    for o in context.selected_objects:
        o.select_set(False)
    out.select_set(True)
    context.view_layer.objects.active = out
    return out
