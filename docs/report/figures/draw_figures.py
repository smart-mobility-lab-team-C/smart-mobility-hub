import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

BLUE, GREY, RED, GREEN = '#dce9f5', '#f2f2f2', '#f8d7d3', '#dff0d8'
FS = 7.0

def canvas(w, h):
    fig = plt.figure(figsize=(w, h), dpi=220)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, w); ax.set_ylim(0, h); ax.axis('off')
    return fig, ax

def box(ax, x, y, text, color=BLUE):
    lines = text.split('\n')
    w = 0.068 * max(len(l) for l in lines) + 0.22
    h = 0.17 * len(lines) + 0.14
    ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h, boxstyle='round,pad=0.02',
                                fc=color, ec='#194669', lw=1.0))
    ax.text(x, y, text, ha='center', va='center', fontsize=FS)
    return (x, y, w, h)

def edge_point(b, tx, ty):
    x, y, w, h = b; dx, dy = tx - x, ty - y
    s = min((w / 2 + 0.03) / abs(dx) if dx else 9e9, (h / 2 + 0.03) / abs(dy) if dy else 9e9)
    return x + dx * s, y + dy * s

def arrow(ax, a, b, label='', rad=0.0, color='#333333', off=(0, 0.09), lfs=6.0):
    p1 = edge_point(a, b[0], b[1]); p2 = edge_point(b, a[0], a[1])
    ax.add_patch(FancyArrowPatch(p1, p2, arrowstyle='-|>', mutation_scale=9, color=color,
                                 lw=0.9, connectionstyle=f'arc3,rad={rad}'))
    if label:
        mx, my = (p1[0] + p2[0]) / 2 + off[0], (p1[1] + p2[1]) / 2 + off[1]
        ax.text(mx, my, label, fontsize=lfs, ha='center', va='center', color='#222222',
                bbox=dict(fc='white', ec='none', pad=0.3, alpha=0.9))

# 1. ROS graph (7.0 x 4.4 in)
fig, ax = canvas(7.0, 4.4)
sim = box(ax, 1.15, 3.95, 'scenario_runner\n(sim, truth, adapters)', GREY)
det = box(ax, 3.55, 3.95, 'passenger_detector')
pred = box(ax, 5.8, 3.95, 'demand_predictor')
traf = box(ax, 1.15, 2.75, 'traffic_monitor')
park = box(ax, 3.55, 2.75, 'parking_manager')
hub = box(ax, 5.8, 2.75, 'hub_coordinator\n(crossing, dispatch)')
route = box(ax, 1.15, 1.55, 'route_planner')
bus = box(ax, 3.55, 1.55, 'bus_manager')
robot = box(ax, 5.8, 1.55, 'robot_manager')
safe = box(ax, 3.55, 0.45, 'safety_supervisor\n(only final velocities)', RED)
met = box(ax, 6.1, 0.45, 'metrics_logger', GREEN)
arrow(ax, sim, det, '/camera/image_raw', off=(0, 0.12)); arrow(ax, det, pred, '/hub/queue', off=(0, 0.12))
arrow(ax, pred, hub, '/hub/demand', off=(0.38, 0)); arrow(ax, sim, traf, '/hub/vehicles', off=(0.42, 0))
arrow(ax, sim, park, '/parking/observed', off=(0.25, 0.08)); arrow(ax, traf, route, '/traffic/edges', off=(0.42, 0))
arrow(ax, hub, bus, '/bus/dock', off=(0.1, 0.12)); arrow(ax, hub, robot, '/crossing/request', off=(0.5, 0))
arrow(ax, route, bus, '/route/compute', off=(0, 0.1)); arrow(ax, route, robot, '', rad=0.25)
arrow(ax, bus, safe, 'candidate', off=(0.3, 0)); arrow(ax, robot, safe, 'candidate', off=(0.35, 0.05))
arrow(ax, safe, sim, 'final /cmd_vel', rad=-0.35, color='#b03020', off=(-0.6, -0.85))
ax.text(0.1, 0.06, 'Blue: decision nodes   Red: sole final-motion authority   Green: observer (no control)   '
        'Not shown: dashboard_marker_publisher (read-only)', fontsize=5.6)
fig.savefig('ros_graph.png'); plt.close(fig)

# 2. Escort FSM (7.0 x 2.3 in)
fig, ax = canvas(7.0, 2.3)
idle = box(ax, 0.45, 1.75, 'IDLE', GREY); pick = box(ax, 1.75, 1.75, 'TO_PICKUP')
wait = box(ax, 3.25, 1.75, 'WAIT_READY'); esc = box(ax, 4.75, 1.75, 'ESCORT')
arr = box(ax, 6.35, 1.75, 'ARRIVED', GREEN)
blk = box(ax, 4.75, 0.45, 'BLOCKED /\nWAIT_CROSSING', GREY)
fail = box(ax, 1.75, 0.45, 'CANCELLED / FAILED /\nSAFE_STOP', RED)
arrow(ax, idle, pick, 'accepted', off=(0, 0.13)); arrow(ax, pick, wait, '≤0.20 m 1 s', off=(0, 0.13))
arrow(ax, wait, esc, 'confirm_ready', off=(0, 0.13)); arrow(ax, esc, arr, '≤0.20 m 1 s', off=(0, 0.13))
arrow(ax, esc, blk, 'edge blocked /\nno token', rad=0.3, off=(-0.55, 0))
arrow(ax, blk, esc, 'new route /\ntoken', rad=0.3, off=(0.55, 0))
arrow(ax, wait, fail, '20 s, no\nreadiness', off=(0.45, 0.05))
arrow(ax, pick, fail, 'cancel, stale odom,\nlatch, NO_ROUTE', off=(-0.6, 0))
fig.savefig('escort_fsm.png'); plt.close(fig)

# 3. Docking FSM (7.0 x 2.2 in)
fig, ax = canvas(7.0, 2.2)
i = box(ax, 0.45, 1.65, 'IDLE', GREY); ap = box(ax, 1.9, 1.65, 'APPROACH')
w = box(ax, 3.5, 1.65, 'WAIT', GREY); dk = box(ax, 5.1, 1.65, 'DOCK')
bd = box(ax, 5.1, 0.45, 'BOARD'); cp = box(ax, 6.5, 0.45, 'COMPLETE', GREEN)
ss = box(ax, 1.9, 0.45, 'SAFE_STOP', RED)
arrow(ax, i, ap, 'DockBus', off=(0, 0.13)); arrow(ax, ap, w, 'C or bay busy', off=(0, 0.13))
arrow(ax, w, dk, 'token + bay', off=(0, 0.13))
arrow(ax, dk, bd, '0.20 m, 0.17 rad,\n1 s, < 0.02 m/s', off=(-0.6, 0))
arrow(ax, bd, cp, 'door closed', off=(0, 0.13))
arrow(ax, ap, ss, 'cancel, stale pose,\nlatch, timeout', off=(-0.6, 0))
fig.savefig('docking_fsm.png'); plt.close(fig)

# 4. Crossing states (7.0 x 2.2 in)
fig, ax = canvas(7.0, 2.2)
u = box(ax, 0.6, 1.65, 'UNKNOWN', RED); cl = box(ax, 2.4, 1.65, 'CLEAR', GREEN)
ow = box(ax, 4.6, 1.65, 'OWNED'); ho = box(ax, 4.6, 0.45, 'HOLD', GREY)
oc = box(ax, 2.4, 0.45, 'OCCUPIED', GREY)
arrow(ax, u, cl, 'fresh, empty 2.0 s', off=(0, 0.13))
arrow(ax, cl, ow, 'ACQUIRE (FIFO) -> token', rad=0.25, off=(0, -0.3))
arrow(ax, ow, cl, 'RELEASE after\nfootprint left C', rad=0.25, off=(0, 0.32))
arrow(ax, ow, ho, 'lease lost\ninside C', rad=0.3, off=(-0.5, 0))
arrow(ax, ho, ow, 'same-token\nRENEW', rad=0.3, off=(0.5, 0))
arrow(ax, cl, oc, 'pedestrian /\nunowned body', off=(-0.5, 0))
ax.text(5.6, 1.65, 'Any stale or invalid input\n-> UNKNOWN (deny entry)', fontsize=6.5, va='center')
fig.savefig('crossing_states.png'); plt.close(fig)
print('ok')
