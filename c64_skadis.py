# Soportes IKEA Skadis para Commodore 64 "breadbin" (montaje vertical, teclado al frente)
# Uso: Blender -b -P c64_skadis.py -- <salida.blend> [dir_renders]
#
# Sistema de coordenadas (mm, 1 BU = 1 mm), vista de montaje:
#   y = 0  -> cara frontal del tablero Skadis (el tablero ocupa y in [0, BOARD_T])
#   -y     -> hacia el espectador;  +z arriba;  x horizontal
#   z = 0  -> superficie de la repisa de las cunas (borde frontal de la C64 apoya aqui)
import bpy, bmesh, math, sys, os, glob
import numpy as np
from mathutils import Matrix, Vector

# ----------------------------------------------------------------- parametros
# Commodore 64 breadbin (MEDIR Y AJUSTAR)
C64_W = 404.0        # ancho (el modelo de referencia se escala a esto)
C64_D = 216.0        # profundidad, queda vertical (el modelo mide 206.3 -> se estira)
REF_SZ = 1.0         # escala del alto: el modelo mide 70.6 sin patas (~75 con patas de goma)
CLR = 1.5            # holgura general entre piezas y carcasa
Y_REDUCE = 4.5       # la carcasa real es mas delgada (eje Y) que el modelo: se resta al grosor
Y_RAMP = 20.0        # ...completo a partir de este grosor, rampa suave cerca de la base

# Modelo de referencia de la carcasa: "Commodore 64 case V 2.1" en MakerWorld (no incluido)
#   https://makerworld.com/en/models/1049608-commodore-64-case-v-2-1
# Descarga el modelo y pon sus STL ensamblados en ./ref_c64 (junto a este script),
# o indica otra carpeta con la variable de entorno C64_REF_DIR.
REF_DIR = os.environ.get("C64_REF_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)) if os.path.isfile(__file__) else os.getcwd(),
    "ref_c64")
ENV_STEP = 0.5       # resolucion del perfil (mm)

# Skadis
BOARD_T = 5.0
SLOT_W, SLOT_H = 5.0, 15.0
PITCH_X, ROW_Z = 40.0, 20.0     # columnas cada 40, filas cada 20 escalonadas 20
Z0 = -5.0                       # centro de la fila k=0 (relativo a la repisa)

# Pegs
TAB_W = 4.4          # ancho del tab (ranura de 5)
NECK_H = 5.0         # alto del cuello del gancho
NECK_L = BOARD_T + 0.5
FINGER_T = 3.5       # grosor del dedo detras del tablero
FINGER_DROP = 8.0    # cuanto baja el dedo bajo el cuello (NECK_H+DROP < SLOT_H)
PIN_H = 6.0          # alto de la espiga recta (<= SLOT_H - FINGER_DROP - margen)
PIN_L = BOARD_T

# Piezas
PLATE_T = 6.0
BEVEL = 0.6
BED = 110.0

# Cuna inferior
CR_XT = 80.0         # columna del primer tab de la cuna derecha (la izquierda es simetrica)
CR_COLS = 2          # columnas Skadis (misma fila) que abarca la cuna: ancho = 40*(n-1) + TAB_W
CR_SHELF_T = 8.0
CR_LIP_T = 4.0
CR_LIP_H = 23.0      # alto del labio/copa (las teclas empiezan a ~24 mm del borde)
CR_HOOK_ROW, CR_PIN_ROW = 0, -2

# Reten superior
# Retenes: la placa con los ganchos va POR ENCIMA del borde superior de la C64 (asi se pueden
# colgar con la C64 ya puesta y no tapan los conectores). El brazo/labio solo cruza zonas sin
# puertos: en el modelo el puerto de cartucho termina en x=156.5 y el user port empieza en x=-188.5.
CL_R_COLS = (220.0,)                       # columna Skadis del reten derecho (fuera de la C64, como v1)
CL_R_ARM = (191.5, 404.0 / 2 + 0.2)        # rango x del brazo/labio derecho (agarre 10.7 mm)
CL_L_COLS = (-220.0,)                      # reten izquierdo: espejo del derecho
CL_L_ARM = (-404.0 / 2 - 0.2, -191.5)      # (el user port empieza en x = -188.5)
CL_ARM_T = 8.0
CL_LIP_T = 4.0
CL_LIP_H = 45.0      # cuanto baja el labio por la cara del teclado (las teclas acaban ~75 mm abajo)
CL_DROP = FINGER_DROP + 1.0   # recorrido vertical al colgar el reten

# Zona de la escena donde se acomodan las piezas de impresion (lejos de la maqueta)
PRINT_ORIGIN = (-130.0, 0.0, -400.0)

# ----------------------------------------------------------------- utilidades
def row_parity(x):
    return int(round((x % (2 * PITCH_X)) / PITCH_X * 2)) % 2   # 0: x=40m, 1: x=40m+20

def slot_bottom(k):
    return Z0 + ROW_Z * k - SLOT_H / 2

def link(obj, coll):
    for c in obj.users_collection:
        c.objects.unlink(obj)
    coll.objects.link(obj)

def get_coll(name):
    c = bpy.data.collections.get(name) or bpy.data.collections.new(name)
    if c.name not in bpy.context.scene.collection.children:
        bpy.context.scene.collection.children.link(c)
    return c

def prism(name, prof_yz, x0, x1):
    """Extruye un perfil (y,z) entre x0 y x1."""
    bm = bmesh.new()
    a = [bm.verts.new((x0, y, z)) for y, z in prof_yz]
    b = [bm.verts.new((x1, y, z)) for y, z in prof_yz]
    caps = [bm.faces.new(a), bm.faces.new(list(reversed(b)))]
    n = len(prof_yz)
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new((a[i], a[j], b[j], b[i]))
    # tapas como n-gon: triangularlas hace fallar el boolean exacto con perfiles largos
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob

def simplify(pts, tol=0.05):
    """Quita puntos repetidos y casi colineales (desviacion < tol mm). Evita triangulos
    degenerados que hacen fallar el boolean exacto."""
    out = []
    for p in pts:
        if out and math.dist(p, out[-1]) < 0.2:
            continue
        out.append(p)
        while len(out) >= 3:
            (ax, ay), (bx, by), (cx, cy) = out[-3:]
            d = math.dist((ax, ay), (cx, cy))
            if d < 1e-9 or abs((bx - ax) * (cy - ay) - (by - ay) * (cx - ax)) / d < tol:
                out.pop(-2)
            else:
                break
    if len(out) > 2 and math.dist(out[0], out[-1]) < 0.2:
        out.pop()
    return out

def difference(base, cutter):
    m = base.modifiers.new("d", 'BOOLEAN')
    m.operation, m.solver, m.object = 'DIFFERENCE', 'EXACT', cutter
    bake(base)
    bpy.data.objects.remove(cutter)
    return base

# ----------------------------------------------------------------- carcasa de referencia
def load_ref():
    """Carga los STL de la carcasa y los lleva a coordenadas de montaje:
    x igual, base contra las placas (y = -PLATE_T), borde frontal abajo (z = CLR)."""
    bm = bmesh.new()
    files = sorted(glob.glob(os.path.join(REF_DIR, "*.stl")))
    assert files, ("no hay STL en " + REF_DIR + " -- descarga el modelo de MakerWorld "
                   "(ver README) o define C64_REF_DIR")
    for f in files:
        bpy.ops.wm.stl_import(filepath=f)
        o = bpy.context.selected_objects[0]
        me = o.data
        bm.from_mesh(me)
        bpy.data.objects.remove(o)
        bpy.data.meshes.remove(me)
    bmesh.ops.triangulate(bm, faces=bm.faces)
    co = np.array([v.co[:] for v in bm.verts])
    (x0, y0, _), (x1, y1, _) = co.min(0), co.max(0)
    sx, sy = C64_W / (x1 - x0), C64_D / (y1 - y0)
    for v in bm.verts:
        x, y, z = v.co
        t = z * REF_SZ
        t -= Y_REDUCE * min(max(t, 0.0) / Y_RAMP, 1.0)
        v.co = Vector(((x - (x0 + x1) / 2) * sx, -(PLATE_T + t), (y - y0) * sy + CLR))
    print(f"Referencia: {x1-x0:.1f} x {y1-y0:.1f} mm -> escala x{sx:.3f} y{sy:.3f}")
    return bm

def ref_envelope(bm, xranges):
    """Perfil de la carcasa en los rangos x dados: por cada altura z (bins de ENV_STEP)
    el grosor t (desde la base) minimo y maximo. Dilatado por CLR."""
    tri = np.array([[v.co[:] for v in f.verts] for f in bm.faces])
    P = [tri[:, 0], tri[:, 1], tri[:, 2]]
    N = int((C64_D + 30) / ENV_STEP)
    tmin, tmax = np.full(N, np.inf), np.full(N, -np.inf)
    xs = np.concatenate([np.linspace(a, b, max(2, int((b - a) / 2) + 1)) for a, b in xranges])
    for x in xs:
        idx, pts = [], []
        for i in range(3):
            a, b = P[i], P[(i + 1) % 3]
            da, db = a[:, 0] - x, b[:, 0] - x
            m = da * db < 0
            u = da[m] / (da[m] - db[m])
            idx.append(np.nonzero(m)[0])
            pts.append((a[m] + (b[m] - a[m]) * u[:, None])[:, 1:])
        idx, pts = np.concatenate(idx), np.concatenate(pts)
        o = np.argsort(idx, kind="stable"); idx, pts = idx[o], pts[o]
        same = idx[:-1] == idx[1:]
        A, B = pts[:-1][same], pts[1:][same]
        n = (np.ceil(np.linalg.norm(B - A, axis=1) / (ENV_STEP * 0.8)).astype(int) + 1)
        rep_ = np.repeat(np.arange(len(A)), n)
        k = np.arange(n.sum()) - np.repeat(np.cumsum(n) - n, n)
        f = k / np.repeat(np.maximum(n - 1, 1), n)
        S = A[rep_] + (B[rep_] - A[rep_]) * f[:, None]
        bins = np.round(S[:, 1] / ENV_STEP).astype(int)
        t = -S[:, 0] - PLATE_T
        ok = (bins >= 0) & (bins < N)
        np.minimum.at(tmin, bins[ok], t[ok]); np.maximum.at(tmax, bins[ok], t[ok])
    tmin[np.isinf(tmin)] = np.nan; tmax[np.isinf(tmax)] = np.nan
    k = int(round(CLR / ENV_STEP))
    lo, hi = np.full(N, np.nan), np.full(N, np.nan)
    for i in range(N):
        w0, w1 = tmin[max(0, i - k):i + k + 1], tmax[max(0, i - k):i + k + 1]
        if not np.all(np.isnan(w1)):
            lo[i], hi[i] = np.nanmin(w0) - CLR, np.nanmax(w1) + CLR
    return lo, hi

def cup_cutter(lo, hi, h_top):
    """Hueco de la cuna: lo que barre la carcasa al bajar en vertical hasta su sitio
    (union acumulada del perfil desde abajo). Devuelve perfil (y,z) y grosor max en h_top."""
    f, b = [], []
    cmin, cmax = np.inf, -np.inf
    for i in range(len(hi)):
        h = i * ENV_STEP
        if h > h_top:
            break
        if not np.isnan(hi[i]):
            cmin, cmax = min(cmin, lo[i]), max(cmax, hi[i])
        if cmax == -np.inf:
            continue
        f.append((-(PLATE_T + cmax), h)); b.append((-(PLATE_T + max(cmin, 0.0)), h))
    f.append((f[-1][0], h_top + 15)); b.append((b[-1][0], h_top + 15))
    return simplify(f + b[::-1]), cmax

def clip_cutter(lo, hi, h_from):
    """Hueco del reten: lo que barre la carcasa (en el marco del reten) mientras el reten
    se acerca al tablero CL_DROP mm mas alto y luego cae a su sitio."""
    di = int(round(CL_DROP / ENV_STEP))
    f, b = [], []
    for i in range(int(h_from / ENV_STEP), len(hi)):
        wl, wh = lo[i:i + di + 1], hi[i:i + di + 1]
        if np.all(np.isnan(wh)):
            continue
        l, u = np.nanmin(wl), np.nanmax(wh)
        if i + di < len(hi) and not np.isnan(hi[i + di]):
            l = -PLATE_T - 3                      # al acercarse barre hasta el tablero
        h = i * ENV_STEP
        f.append((-(PLATE_T + u), h)); b.append((-(PLATE_T + max(l, -PLATE_T - 3)), h))
    return simplify(f + b[::-1]), f

def box(name, x0, x1, y0, y1, z0, z1):
    return prism(name, [(y0, z0), (y1, z0), (y1, z1), (y0, z1)], x0, x1)

def bake(ob):
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(ob.evaluated_get(dg))
    for m in list(ob.modifiers):
        ob.modifiers.remove(m)
    old = ob.data
    ob.data = me
    bpy.data.meshes.remove(old)

def union(name, parts, bevel=BEVEL):
    base = parts[0]
    for t in parts[1:]:
        m = base.modifiers.new("u", 'BOOLEAN')
        m.operation, m.solver, m.object = 'UNION', 'EXACT', t
    bake(base)
    for t in parts[1:]:
        bpy.data.objects.remove(t)
    base.name = base.data.name = name
    if bevel:
        backup = base.data.copy()
        m = base.modifiers.new("bevel", 'BEVEL')
        m.width, m.segments, m.limit_method, m.angle_limit = bevel, 2, 'ANGLE', math.radians(40)
        m.harden_normals = False
        bake(base)
        if non_manifold(base):
            print(f"[{name}] bevel produjo geometria non-manifold; se omite")
            base.data = backup
        else:
            bpy.data.meshes.remove(backup)
    return base

def non_manifold(ob):
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    n = sum(1 for e in bm.edges if not e.is_manifold)
    bm.free()
    return n

def skadis_pegs(cols, hook_row, pin_row, tag):
    """Un gancho + una espiga (ancho TAB_W) centrados en cada columna x de `cols`."""
    out = []
    for i, xc in enumerate(cols):
        out += skadis_peg_pair(xc - TAB_W / 2, xc + TAB_W / 2, hook_row, pin_row, f"{tag}_{i}")
    return out

def skadis_peg_pair(xa, xb, hook_row, pin_row, tag):
    zb = slot_bottom(hook_row)
    hook = prism(tag + "_hook", [
        (-1, zb), (NECK_L, zb), (NECK_L, zb - FINGER_DROP + 1.5),
        (NECK_L + 1.5, zb - FINGER_DROP), (NECK_L + FINGER_T, zb - FINGER_DROP),
        (NECK_L + FINGER_T, zb + NECK_H - 1), (NECK_L + FINGER_T - 1, zb + NECK_H),
        (-1, zb + NECK_H)], xa, xb)
    zp = slot_bottom(pin_row)
    pin = prism(tag + "_pin", [
        (-1, zp), (PIN_L - 0.8, zp), (PIN_L, zp + 0.8),
        (PIN_L, zp + PIN_H - 0.8), (PIN_L - 0.8, zp + PIN_H), (-1, zp + PIN_H)], xa, xb)
    return [hook, pin]

# ----------------------------------------------------------------- piezas
def make_cradle(x_t, name, env):
    assert row_parity(x_t) == CR_HOOK_ROW % 2 == CR_PIN_ROW % 2, "columna/fila de la cuna no coinciden"
    cols = [x_t + PITCH_X * i for i in range(CR_COLS)]
    x0, x1 = cols[0] - TAB_W / 2, cols[-1] + TAB_W / 2   # tabs al ras de ambas caras; cama = x0
    cut_prof, t_lip = cup_cutter(*env, CR_LIP_H)
    y_out = -(PLATE_T + t_lip) - CR_LIP_T
    z_bot = slot_bottom(CR_PIN_ROW) - 5.5
    S = CR_SHELF_T
    gy = 0.6 * (-y_out - PLATE_T)
    gz = min(0.8 * gy, -z_bot - S - 6)
    prof = [
        (0, z_bot), (0, CR_LIP_H), (y_out + 2, CR_LIP_H), (y_out, CR_LIP_H - 2),
        (y_out, -S + 2), (y_out + 2, -S),
        (-PLATE_T - gy, -S), (-PLATE_T, -S - gz),               # cartela
        (-PLATE_T, z_bot)]
    body = prism(name + "_body", prof, x0, x1)
    body = difference(body, prism(name + "_cut", cut_prof, x0 - 1, x1 + 1))
    ob = union(name, [body] + skadis_pegs(cols, CR_HOOK_ROW, CR_PIN_ROW, name))
    ob["seat_depth_mm"] = round(t_lip, 1)
    return ob

def make_top_clip(name, env, cols, arm_x):
    """Reten superior. Un solo prisma (labio + brazo + placa que sube por encima de la C64)
    al que se le restan:
      - en el rango del brazo: el hueco barrido por la carcasa al colgar el reten
      - fuera del brazo: todo menos la placa (para no tapar los puertos traseros)."""
    p = row_parity(cols[0])
    assert all(row_parity(c) == p for c in cols), "las columnas del reten no estan en la misma fila"
    ax0, ax1 = arm_x
    x0 = min(min(cols) - TAB_W / 2, ax0)
    x1 = max(max(cols) + TAB_W / 2, ax1)
    xc = C64_W / 2 + 0.2                  # borde de la C64 (+ margen)
    top = C64_D + CLR                     # punto mas alto de la carcasa
    zlow = top - CL_LIP_H
    _, front = clip_cutter(*env, zlow - 3)
    arm_z = max(z for _, z in front)      # cara inferior del brazo (top + holgura)
    T = arm_z + CL_ARM_T
    if min(abs(c) for c in cols) - TAB_W / 2 > C64_W / 2 + CLR:
        # columnas fuera del ancho de la C64: la placa puede bajar junto a la carcasa;
        # fila mas baja que deja la espiga arriba de la cartela del brazo
        kh = min(k for k in range(0, 40) if k % 2 == p and slot_bottom(k) >= zlow + 2
                 and slot_bottom(k + 2) + PIN_H + 4 >= T + 14)
    else:
        kh = min(k for k in range(0, 40) if k % 2 == p and slot_bottom(k) >= arm_z)   # gancho (abajo)
    kp = kh + 2                                                                     # espiga (arriba)
    z_top = slot_bottom(kp) + PIN_H + 4
    t_in = max(-y for y, z in front if z >= zlow) - PLATE_T
    y_in = -(PLATE_T + t_in)
    y_out = y_in - CL_LIP_T
    body = prism(name + "_body", [
        (0, zlow), (0, z_top), (-PLATE_T, z_top), (-PLATE_T, T + 12), (-PLATE_T - 12, T),
        (y_out + 2, T), (y_out, T - 2), (y_out, zlow + 2), (y_out + 2, zlow)], x0, x1)
    cut_prof, _ = clip_cutter(*env, zlow - 3)
    ca, cb = max(ax0, -xc), min(ax1, xc)  # brazo dentro del ancho de la C64
    body = difference(body, prism(name + "_cut", cut_prof, ca - 1, cb + 1))
    # dentro de la C64 pero fuera del brazo: solo queda la placa (no tapar puertos)
    trim = [(1, zlow - 1), (1, arm_z), (-PLATE_T, arm_z), (-PLATE_T, z_top + 1),
            (y_out - 1, z_top + 1), (y_out - 1, zlow - 1)]
    for a, b in ((max(x0, -xc) - 1, ca), (cb, min(x1, xc) + 1)):
        if b - a > 1.01:
            body = difference(body, prism(name + "_trim", trim, a, b))
    # fuera de la C64: marco placa + brazo + labio (se quita el espacio entre placa y labio)
    gap = [(y_in, zlow - 1), (-PLATE_T, zlow - 1), (-PLATE_T, arm_z - 8), (-PLATE_T - 8, arm_z),
           (y_in + 2, arm_z), (y_in, arm_z - 2)]
    for a, b in ((x0 - 1, -xc), (xc, x1 + 1)):
        if b - a > 1.01:
            body = difference(body, prism(name + "_gap", gap, a, b))
    ob = union(name, [body] + skadis_pegs(cols, kh, kp, name))
    ob["hook_row"], ob["pin_row"] = kh, kp
    ob["grip_mm"] = round(min(ax1, C64_W / 2) - max(ax0, -C64_W / 2), 1)
    return ob

def mirror_x(src, name):
    me = src.data.copy()
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.transform(bm, matrix=Matrix.Scale(-1, 4, (1, 0, 0)), verts=bm.verts)
    bmesh.ops.reverse_faces(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    me.name = name
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob

def print_copy(src, name, bed_face_min_x, offset_x, coll):
    """Copia acostada sobre la cara del tab (cama), centrada en (offset_x, 0), z>=0."""
    me = src.data.copy()
    me.transform(Matrix.Rotation(math.radians(-90 if bed_face_min_x else 90), 4, 'Y'))
    xs = [v.co.x for v in me.vertices]; ys = [v.co.y for v in me.vertices]; zs = [v.co.z for v in me.vertices]
    me.transform(Matrix.Translation((offset_x - (min(xs) + max(xs)) / 2, -(min(ys) + max(ys)) / 2, -min(zs))))
    me.name = name
    ob = bpy.data.objects.new(name, me)
    coll.objects.link(ob)
    return ob

def check_bed_fit(ob):
    d = ob.dimensions
    ok = all(v <= BED + 1e-6 for v in d)
    nm = non_manifold(ob)
    print(f"  {ob.name:14s} {d.x:6.1f} x {d.y:6.1f} x {d.z:6.1f} mm   "
          f"{'OK' if ok else 'EXCEDE 110'}   non-manifold={nm}   tris={sum(len(p.vertices)-2 for p in ob.data.polygons)}")
    return ok and nm == 0

# ----------------------------------------------------------------- maqueta
def make_board():
    x0, x1, z0, z1 = -300, 300, -100, 320
    board = box("Skadis_board", x0, x1, 0, BOARD_T, z0, z1)
    bm = bmesh.new()
    for k in range(-6, 16):
        zc = Z0 + ROW_Z * k
        if zc - SLOT_H / 2 < z0 + 8 or zc + SLOT_H / 2 > z1 - 8:
            continue
        xc = (k % 2) * PITCH_X / 2 - 8 * PITCH_X
        while xc <= x1 - 10:
            if xc >= x0 + 10:
                r = bmesh.ops.create_cube(bm, size=1)["verts"]
                bmesh.ops.transform(bm, verts=r, matrix=Matrix.Translation((xc, BOARD_T / 2, zc)) @
                                    Matrix.Diagonal((SLOT_W, BOARD_T + 4, SLOT_H, 1)))
            xc += PITCH_X
    me = bpy.data.meshes.new("slots"); bm.to_mesh(me); bm.free()
    cut = bpy.data.objects.new("slots", me); bpy.context.scene.collection.objects.link(cut)
    m = board.modifiers.new("slots", 'BOOLEAN'); m.operation, m.solver, m.object = 'DIFFERENCE', 'FAST', cut
    bake(board); bpy.data.objects.remove(cut)
    return board

def make_c64(bm):
    me = bpy.data.meshes.new("C64_breadbin")
    bm.to_mesh(me)
    ob = bpy.data.objects.new("C64_breadbin", me)
    bpy.context.scene.collection.objects.link(ob)
    return ob

# ----------------------------------------------------------------- escena
def setup_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    s = bpy.context.scene
    s.unit_settings.system = 'METRIC'
    s.unit_settings.scale_length = 0.001
    s.unit_settings.length_unit = 'MILLIMETERS'
    return s

def color(ob, rgba):
    ob.color = rgba

def look_at(cam, loc, target):
    cam.location = loc
    cam.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat('-Z', 'Y').to_euler()

def render(scene, cam, path, show, xray=False, ortho=None):
    for c in bpy.data.collections:
        c.hide_render = c.name not in show
    cam.data.type = 'ORTHO' if ortho else 'PERSP'
    if ortho:
        cam.data.ortho_scale = ortho
    scene.display.shading.show_xray = xray
    scene.display.shading.xray_alpha = 0.45
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)

def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out_blend = argv[0] if argv else os.path.abspath("c64_skadis_mount.blend")
    render_dir = argv[1] if len(argv) > 1 else None

    scene = setup_scene()
    cp, cprint, cref = get_coll("Preview"), get_coll("Print"), get_coll("BedRef")

    # piezas en posicion de montaje
    ref = load_ref()
    span = PITCH_X * (CR_COLS - 1)
    xr_l = -CR_XT - span                                  # cuna izquierda simetrica
    cr_env = ref_envelope(ref, [(CR_XT - TAB_W / 2 - 1, CR_XT + span + TAB_W / 2 + 1),
                                (xr_l - TAB_W / 2 - 1, xr_l + span + TAB_W / 2 + 1)])
    clr_env = ref_envelope(ref, [(max(CL_R_ARM[0], -C64_W / 2), min(CL_R_ARM[1], C64_W / 2))])
    cll_env = ref_envelope(ref, [(max(CL_L_ARM[0], -C64_W / 2), min(CL_L_ARM[1], C64_W / 2))])
    cr_r = make_cradle(CR_XT, "Cradle_R", cr_env)
    cr_l = make_cradle(xr_l, "Cradle_L", cr_env)
    cl_r = make_top_clip("TopClip_R", clr_env, CL_R_COLS, CL_R_ARM)
    cl_l = make_top_clip("TopClip_L", cll_env, CL_L_COLS, CL_L_ARM)
    print(f"  Retenes: agarre R={cl_r['grip_mm']} mm, L={cl_l['grip_mm']} mm")
    board, c64 = make_board(), make_c64(ref)
    print(f"  Copa de la cuna: {cr_r['seat_depth_mm']} mm de grosor de carcasa a la altura del labio")
    for ob, col in [(cr_r, (0.95, 0.45, 0.1, 1)), (cr_l, (0.95, 0.45, 0.1, 1)),
                    (cl_r, (0.15, 0.5, 0.9, 1)), (cl_l, (0.15, 0.5, 0.9, 1)),
                    (board, (0.85, 0.75, 0.6, 1)), (c64, (0.55, 0.45, 0.33, 1))]:
        link(ob, cp); color(ob, col)

    # piezas para imprimir
    items = [(cr_r, "PRINT_Cradle_x2", True, (0.95, 0.45, 0.1, 1)),
             (cl_r, "PRINT_TopClip_R", False, (0.15, 0.5, 0.9, 1)),
             (cl_l, "PRINT_TopClip_L", True, (0.15, 0.5, 0.9, 1))]
    print("\nPiezas para imprimir (cama max %.0f mm):" % BED)
    all_ok = True
    for i, (src, name, minx, col) in enumerate(items):
        ob = print_copy(src, name, minx, i * 130.0, cprint); color(ob, col)
        ob.location = PRINT_ORIGIN
        bpy.context.view_layer.update()
        all_ok &= check_bed_fit(ob)
        bm = bmesh.new()
        bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=BED / 2)
        me = bpy.data.meshes.new(f"bed_{i}"); bm.to_mesh(me); bm.free()
        bed = bpy.data.objects.new(f"Bed110_{i}", me); bed.location = Vector(PRINT_ORIGIN) + Vector((i * 130.0, 0, -0.5))
        cref.objects.link(bed); color(bed, (0.3, 0.3, 0.3, 1))
    print(f"  Reten: gancho en fila {cl_r['hook_row']}, espiga en fila {cl_r['pin_row']}")
    if not all_ok:
        raise SystemExit("ERROR: alguna pieza excede la cama o no es manifold")

    # guardar script dentro del .blend para poder ajustar parametros
    txt = bpy.data.texts.new("c64_skadis.py")
    txt.write(open(__file__ if "__file__" in globals() else sys.argv[sys.argv.index("-P") + 1]).read())

    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.display.shading.color_type = 'OBJECT'
    scene.display.shading.light = 'STUDIO'
    scene.display.shading.show_cavity = True
    scene.render.resolution_x, scene.render.resolution_y = 1400, 1000
    scene.world = bpy.data.worlds.new("w"); scene.world.color = (0.9, 0.9, 0.92)
    camd = bpy.data.cameras.new("cam"); camd.clip_end = 10000; camd.lens = 40
    cam = bpy.data.objects.new("Camera", camd); scene.collection.objects.link(cam); scene.camera = cam

    if render_dir:
        os.makedirs(render_dir, exist_ok=True)
        look_at(cam, (-420, -780, 420), (0, -40, 90))
        render(scene, cam, os.path.join(render_dir, "01_preview.png"), {"Preview"})
        look_at(cam, (800, -60, 100), (0, -60, 100))
        render(scene, cam, os.path.join(render_dir, "02_side_xray.png"), {"Preview"}, xray=True, ortho=420)
        look_at(cam, (420, -45, 200), (0, -45, 200))
        render(scene, cam, os.path.join(render_dir, "03_clip_detail.png"), {"Preview"}, xray=True, ortho=110)
        look_at(cam, (420, -40, -5), (0, -40, -5))
        render(scene, cam, os.path.join(render_dir, "04_cradle_detail.png"), {"Preview"}, xray=True, ortho=100)
        o = Vector(PRINT_ORIGIN); look_at(cam, o + Vector((130, -330, 260)), o + Vector((130, 0, 15)))
        render(scene, cam, os.path.join(render_dir, "05_print.png"), {"Print", "BedRef"})

    scene.display.shading.show_xray = False
    for c in bpy.data.collections:
        c.hide_render = False
    cref.hide_viewport = False
    bpy.ops.wm.save_as_mainfile(filepath=out_blend)
    print("Guardado:", out_blend)

main()
